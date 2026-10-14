"""Зеркало моего битборд-алгоритма на чистом Python + фаззинг против numba
+ трассировка родителя сбойной позиции с этикетками."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import random
import numpy as np
from engine.bitboard import (
    load_position, compute_winning_position, possible_moves,
    possible_non_losing_moves, play_bit,
)

WIDTH, HEIGHT, H1 = 7, 6, 7
BOTTOM = sum(1 << (c * H1) for c in range(WIDTH))
BOARD = BOTTOM * ((1 << HEIGHT) - 1)


def py_cwp(position, mask):
    r = (position << 1) & (position << 2) & (position << 3)
    for sh in (H1, H1 - 1, H1 + 1):
        p = (position << sh) & (position << 2 * sh)
        r |= p & (position << 3 * sh)
        r |= p & (position >> sh)
        p = (position >> sh) & (position >> 2 * sh)
        r |= p & (position << sh)
        r |= p & (position >> 3 * sh)
    return r & (BOARD ^ mask)


def cwp_bruteforce(position, mask):
    """Грубая сила: для каждой пустой клетки ставим камень и ищем четвёрку сканом."""
    res = 0
    empty = BOARD ^ mask
    while empty:
        b = empty & -empty
        empty ^= b
        pos2 = position | b
        cells = [(i // H1, i % H1) for i in range(WIDTH * H1) if pos2 >> i & 1]
        s = set(cells)
        found = False
        for cc, rr in cells:
            for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
                if (cc - dc, rr - dr) not in s and (cc + dc, rr + dr) in s \
                        and (cc + 2 * dc, rr + 2 * dr) in s and (cc + 3 * dc, rr + 3 * dr) in s:
                    found = True
                    break
            if found:
                break
        if found:
            res |= b
    return res


def has_four(position):
    cells = [(i // H1, i % H1) for i in range(WIDTH * H1) if position >> i & 1]
    s = set(cells)
    for cc, rr in cells:
        for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
            if all((cc + k * dc, rr + k * dr) in s for k in range(4)):
                return True
    return False


def cwp_bruteforce_fast(position, mask):
    res = 0
    empty = BOARD ^ mask
    while empty:
        b = empty & -empty
        empty ^= b
        if has_four(position | b):
            res |= b
    return res


def py_pnl(position, mask, expand_semantics=True):
    """possible_non_losing: точная расширенная семантика 'не отдать победу немедленно'.

    Прямое соответствие определению: ход X не проигрышный, когда после него у
    соперника нет немедленно играбельной выигрышной клетки. Отдельно есть
    понсовская версия с forced-логикой для сравнения форм.
    """
    possible = (mask + BOTTOM) & BOARD
    opp = position ^ mask
    res = 0
    while possible:
        b = possible & -possible
        possible ^= b
        m2 = mask | b
        opp_threats_after = py_cwp(opp, m2) & ((m2 + BOTTOM) & BOARD)
        if opp_threats_after == 0:
            res |= b
    return res


def decode(bits):
    return sorted((i // H1, i % H1) for i in range(WIDTH * H1) if bits >> i & 1)


def random_playout(depth):
    position = 0
    mask = 0
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
        position = position & mask  # XOR уже сделал полусумму; нормализуем к схеме
    return position, mask


def main():
    random.seed(7)
    print("--- фаззинг cwp: python-зеркало против bruteforce (600 случайных досок) ---")
    bad = 0
    for i in range(600):
        pos, mask = random_playout(random.randint(4, 40))
        a = py_cwp(pos, mask)
        b = cwp_bruteforce_fast(pos, mask)
        if a != b:
            bad += 1
            if bad <= 5:
                print(f"  cwp расхождение: mirror={decode(a)} bf={decode(b)}")
                print(f"    mask={decode(mask)}")
    print(f"cwp: расхождений {bad}/600")

    print("--- фаззинг cwp: numba против bruteforce ---")
    bad = 0
    for i in range(600):
        pos, mask = random_playout(random.randint(4, 40))
        a = int(compute_winning_position(np.uint64(pos), np.uint64(mask)))
        b = cwp_bruteforce_fast(pos, mask)
        if a != b:
            bad += 1
            if bad <= 5:
                print(f"  numba cwp расхождение: numba={decode(a)} bf={decode(b)}")
    print(f"cwp numba: расхождений {bad}/600")

    print("--- фаззинг possible_non_losing: numba против расширенной семантики ---")
    bad = 0
    forced_zero_mismatch = 0
    for i in range(600):
        pos, mask = random_playout(random.randint(4, 40))
        a = int(possible_non_losing_moves(np.uint64(pos), np.uint64(mask)))
        b = py_pnl(pos, mask)
        if a != b:
            bad += 1
            if bad <= 8:
                pm = (mask + BOTTOM) & BOARD
                print(f"  pnl расхождение: numba={decode(a)} exact={decode(b)}")
                print(f"    moves={len(decode(mask))} possible={decode(pm)}")
    print(f"pnl: расхождений {bad}/600")

    print("--- смок-проверки negotiator-обёрток на '444' ---")
    p, m, mv = load_position("444")
    print("позиция 444: movement=", mv, "Возможные после фильтра:",
          decode(int(possible_non_losing_moves(np.uint64(p), np.uint64(m)))))


if __name__ == "__main__":
    main()
