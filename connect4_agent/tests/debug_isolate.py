"""Отладочная изоляция: (1) юнит-тесты битовых примитивов; (2) чистый alpha-beta
без ТТ и без PVS против моего солвера на первых позициях Test_L3_R1."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from numba import njit, uint64, types

from engine.bitboard import (
    load_position, compute_winning_position, possible_non_losing_moves,
    play_bit, BOTTOM_COL,
)
from engine.solver_numba import SolverEngine, _negamax

U = np.uint64


def check(name, cond):
    print(("OK  " if cond else "FAIL"), name, flush=True)
    return cond


def test_primitives():
    print("--- юнит-тесты примитивов ---")
    ok = True
    # вертикаль: фишки в колонке 0 ряды 0,1,2 => завершение на бите 3
    pos = U(1) | U(2) | U(4)
    ok &= check("vertical completion bit 3", int(compute_winning_position(pos, pos)) == 8)
    # два в колонке и один камень => пусто
    ok &= check("two stones -> none", int(compute_winning_position(U(1) | U(2), U(1) | U(2))) == 0)
    ok &= check("one stone -> none", int(compute_winning_position(U(1), U(1))) == 0)
    # горизонталь: биты 0, 7, 14 => завершение на бите 21
    pos = U(1) | U(1 << 7) | U(1 << 14)
    ok &= check("horizontal completion bit 21", int(compute_winning_position(pos, pos)) == (1 << 21))
    # диагональ шаг 8: биты 0, 8, 16 => бит 24
    pos = U(1) | U(1 << 8) | U(1 << 16)
    ok &= check("diag up-right completion bit 24", int(compute_winning_position(pos, pos)) == (1 << 24))
    # диагональ шаг 6: биты 0, 6, 12 => бит 18
    pos = U(1) | U(1 << 6) | U(1 << 12)
    ok &= check("diag down-right completion bit 18", int(compute_winning_position(pos, pos)) == (1 << 18))
    # позиция после "112233": камни A в битах 0, 7, 14; B в битах 1, 8, 15
    pos = U(1) | U(1 << 7) | U(1 << 14)
    mask = pos | U(2) | U(8) | U(15)
    ok &= check('"112233" -> A wins via bit21', int(compute_winning_position(pos, mask)) == (1 << 21))
    return ok


@njit(types.int64(uint64, uint64, types.int64, types.int64, types.int64), nogil=True)
def pure_negamax(position, mask, moves, alpha, beta):
    possible = possible_non_losing_moves(position, mask)
    if possible == np.uint64(0):
        return -((42 - moves) // 2)
    if moves >= 40:
        return 0
    lo = -((40 - moves) // 2)
    if alpha < lo:
        alpha = lo
        if alpha >= beta:
            return alpha
    hi = (41 - moves) // 2
    if beta > hi:
        beta = hi
        if alpha >= beta:
            return beta
    for col in range(7):
        move_bit = possible & BOTTOM_COL[col]
        if move_bit != np.uint64(0):
            cpos, cmask = play_bit(position, mask, move_bit)
            s = -pure_negamax(cpos, cmask, moves + 1, -beta, -alpha)
            if s >= beta:
                return s
            if s > alpha:
                alpha = s
    return alpha


def main():
    if not test_primitives():
        print(">>> Примитивы врут — ошибка в битовых операциях.")
        return

    data = (ROOT / "tests" / "data" / "Test_L3_R1").read_text().splitlines()
    positions = [line.rsplit(None, 1) for line in data[:30]]

    eng = SolverEngine(max_gb=0.05)
    tt = [eng.tt["keys"], eng.tt["scores"], eng.tt["metas"], eng.tt["depths"], eng.tt["pairs"]]
    scratch = [eng._sc_row, eng._col_row, eng._nodes]

    pure_bad = full_bad = 0
    print("--- сравнение на 30 позициях Test_L3_R1 (полное окно -22..23) ---")
    for seq, exp_s in positions:
        exp = int(exp_s)
        p, m, mv = load_position(seq)
        pure = int(pure_negamax(U(p), U(m), mv, -22, 23))
        full = int(_negamax(U(p), U(m), mv, -22, 23, *tt, *scratch))
        mark_p = "OK " if pure == exp else "BAD"
        mark_f = "OK " if full == exp else "BAD"
        if pure != exp:
            pure_bad += 1
        if full != exp:
            full_bad += 1
        print(f"{seq}: file={exp:3d}  pure={pure:3d}[{mark_p}]  full={full:3d}[{mark_f}]", flush=True)
    print(f"итог: pure ошибок {pure_bad}/30, full ошибок {full_bad}/30")


if __name__ == "__main__":
    main()
