"""Хирургическая проба: (1) фаззинг фильтра на полных досках против гравитационного
оракула; (2) спуск по детям сбойных позиций с оценками «чистого» движка (без ТТ),
медленного эталона и фильтром на каждом узле."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import random
import numpy as np
from numba import njit, uint64, types

from engine.bitboard import (
    load_position, compute_winning_position, possible_non_losing_moves,
    play_bit, BOTTOM_COL,
)
from engine.solver_numba import _negamax
from engine.transposition_table import allocate_transposition_table
from debug_slow import build_cols, solve_slow

WIDTH, HEIGHT, H1 = 7, 6, 7
BOTTOM = sum(1 << (c * H1) for c in range(WIDTH))
BOARD = BOTTOM * ((1 << HEIGHT) - 1)


def decode_cells(bits):
    return sorted((i // H1, i % H1) for i in range(49) if bits >> i & 1)


def has_four(position):
    cells = [(i // H1, i % H1) for i in range(49) if position >> i & 1]
    s = set(cells)
    for cc, rr in cells:
        for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
            if all((cc + k * dc, rr + k * dr) in s for k in range(4)):
                return True
    return False


def opp_wins_immediately_after(position, mask, move_bit):
    """Гравитационный оракул: после нашего хода у соперника есть немедленный
    играбельный выигрыш (четырки достраиваются только по настоящим камням)."""
    m2 = mask | move_bit
    opp = position ^ m2  # камни соперника в новой позиции (после ^=)
    playable = (m2 + BOTTOM) & BOARD & ~m2
    while playable:
        b = playable & -playable
        playable ^= b
        if has_four(opp | b):
            return True
    return False


def pnl_gravity_oracle(position, mask):
    possible = (mask + BOTTOM) & BOARD & ~mask
    res = 0
    while possible:
        b = possible & -possible
        possible ^= b
        if not opp_wins_immediately_after(position, mask, b):
            res |= b
    return res


def random_playout(depth):
    position = mask = 0
    for _ in range(depth):
        allowed = []
        for c in range(WIDTH):
            b = (mask + (1 << (c * H1))) & BOARD & ~mask
            if b:
                allowed.append(b)
        if not allowed:
            break
        b = random.choice(allowed)
        position = position ^ mask
        mask = mask | b
    return position, mask


NEW_TT = None


def fresh_tt(max_gb=0.01):
    tt = allocate_transposition_table(max_gb=max_gb)
    return [tt["keys"], tt["scores"], tt["metas"], tt["depths"], tt["pairs"]]


SCR = {}


def scratch():
    if "s" not in SCR:
        sc = np.zeros((42, 7), dtype=np.int64)
        cr = np.zeros((42, 7), dtype=np.int8)
        nd = np.zeros(1, dtype=np.int64)
        SCR["s"] = [sc, cr, nd]
    return SCR["s"]


def pure_solve(position, mask, moves):
    """Полный-окна чистый поиск без ТТ: максимально честное значение ядра."""
    tt = fresh_tt()
    sc, cr, nd = scratch()
    return int(_negamax(np.uint64(position), np.uint64(mask), moves, -22, 23, *tt, sc, cr, nd))


def main():
    random.seed(11)
    print("--- фаззинг фильтра на ПОЛНЫХ досках (33..41 камней) ---")
    bad = 0
    for i in range(300):
        pos, mask = random_playout(random.randint(33, 41))
        a = int(possible_non_losing_moves(np.uint64(pos), np.uint64(mask)))
        b = pnl_gravity_oracle(pos, mask)
        if ((a & (mask + BOTTOM)) | 0) != ((b & (mask + BOTTOM)) | 0):
            # сравниваем только играбельные клетки (формула добавляет защиту «не под угрозой»)
            a_play = a & (mask + BOTTOM) & BOARD
            b_play = b & (mask + BOTTOM) & BOARD
            if a_play != b_play:
                bad += 1
                if bad <= 5:
                    print(f"  pnl: numba_play={decode_cells(a_play)} oracle={decode_cells(b_play)}")
                    print(f"    stones={len(decode_cells(mask))}")
    print(f"фильтр (играбельные): расхождений {bad}/300")

    for seed in ("52677675164321472411331752454", "7422341735647741166133573473242566"):
        print("=" * 72)
        p, m, mv = load_position(seed)
        cols, moves, mover = build_cols(seed)
        mine = None  # lazily fresh
        print(f"ПОЗИЦИЯ {seed}  камней={moves} истина={solve_slow(cols, moves, mover=mover)}")
        pnl = int(possible_non_losing_moves(np.uint64(p), np.uint64(m)))
        oracle = pnl_gravity_oracle(p, m)
        print(f"  фильтр numba={decode_cells(pnl)}  оракул={decode_cells(oracle)}")
        print("  дети (истина | чистый движок):")
        for c in range(7):
            if len(cols[c]) >= HEIGHT:
                continue
            seq_c = seed + str(c + 1)
            pp, mm, mvv = load_position(seq_c)
            cols_c, moves_c, mover_c = build_cols(seq_c)
            slow_c = solve_slow(cols_c, moves_c, mover=mover_c)
            pure_c = pure_solve(pp, mm, mvv)
            mark = "OK " if slow_c == pure_c else "!!!"
            print(f"    +{c + 1}: slow={slow_c:3d} pure={pure_c:3d} [{mark}]  "
                  f" Spirit родителя: slow={-slow_c:3d} pure={-pure_c:3d}")
    print("=" * 72)


if __name__ == "__main__":
    main()
