"""Поиск минимального префикса, на котором движок впервые расходится с эталоном."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from engine.bitboard import load_position
from engine.solver_numba import SolverEngine

sys.path.insert(0, str(ROOT / "tests"))
from debug_slow import build_cols, solve_slow  # noqa: E402

SEEDS = [
    "7422341735647741166133573473242566",
    "65214673556155731566316327373221417",
    "52677675164321472411331752454",
    "233377345754465174223731671122611552",
]


def main():
    eng = SolverEngine(max_gb=0.05)
    for seed in SEEDS:
        # первый расходящийся префикс
        first = None
        for k in range(10, len(seed) + 1):
            seq = seed[:k]
            p, m, mv = load_position(seq)
            try:
                mine = eng.solve(np.uint64(p), np.uint64(m), mv)
            except ValueError:
                continue
            cols, moves, mover = build_cols(seq)
            slow = solve_slow(cols, moves, mover=mover)
            if mine != slow:
                first = (k, mine, slow)
                break
        if not first:
            print(f"{seed[:24]}...:{seed[-12:]}: расхождений нет до конца")
            continue
        k, mine, slow = first
        seq = seed[:k]
        print(f"МИНИМУМ для {seed[:16]}...: prefix len={k}  seq={seq}  mine={mine} slow={slow}")
        # этапы последних 6 префиксов
        for kk in range(max(10, k - 6), k + 1):
            s = seed[:kk]
            p, m, mv = load_position(s)
            mine_k = eng.solve(np.uint64(p), np.uint64(m), mv)
            cols, moves, mover = build_cols(s)
            slow_k = solve_slow(cols, moves, mover=mover)
            mark = "  " if mine_k == slow_k else "!!"
            print(f"  {mark} len={kk} moves={moves} mine={mine_k:3d} slow={slow_k:3d} seq={s}")
        # дети минимального расхождение
        print("  дети минимального случая:")
        cols, _, _ = build_cols(seq)
        p, m, mv = load_position(seq)
        for c in range(7):
            if len(cols[c]) >= 6:
                continue
            seq_child = seq + str(c + 1)
            pp, mm, mvv = load_position(seq_child)
            mine_c = eng.solve(np.uint64(pp), np.uint64(mm), mvv)
            cols_c, moves_c, mover_c = build_cols(seq_child)
            slow_c = solve_slow(cols_c, moves_c, mover=mover_c)
            print(f"    +{c + 1}: mine={mine_c:3d} slow={slow_c:3d} {'OK' if mine_c == slow_c else 'РАСХОЖДЕНИЕ'}")
        break


if __name__ == "__main__":
    main()
