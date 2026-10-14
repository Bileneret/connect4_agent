"""Полное зеркало _negamax на python-целых (без numba). Сверка против медленного
эталона на детях 34-каменной позиции; при расхождении — трассировка."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from engine.bitboard import load_position
from debug_slow import build_cols, solve_slow

WIDTH, HEIGHT, H1 = 7, 6, 7
TOTAL = 42
BOTTOM = sum(1 << (c * H1) for c in range(WIDTH))
BOARD = BOTTOM * ((1 << HEIGHT) - 1)
BOTTOM_COL = [1 << (c * H1) for c in range(WIDTH)]
COLUMN_ORDER = [3, 2, 4, 1, 5, 0, 6]

COLS_POS = {}
SC_ROW = {}
COL_CH = {}
NODES = 0
TRACE = False


def cwp(position, mask):
    r = (position << 1) & (position << 2) & (position << 3)
    p = (position << H1) & (position << 2 * H1)
    r |= p & (position << 3 * H1)
    r |= p & (position >> H1)
    p = (position >> H1) & (position >> 2 * H1)
    r |= p & (position << H1)
    r |= p & (position >> 3 * H1)
    for sh in (H1 - 1, H1 + 1):
        p = (position << sh) & (position << 2 * sh)
        r |= p & (position << 3 * sh)
        r |= p & (position >> sh)
        p = (position >> sh) & (position >> 2 * sh)
        r |= p & (position << sh)
        r |= p & (position >> 3 * sh)
    return r & (BOARD ^ mask)


def can_win_next(position, mask):
    return (cwp(position, mask) & ((mask + BOTTOM) & BOARD & ~mask)) != 0


def possible_non_losing(position, mask):
    possible = (mask + BOTTOM) & BOARD
    opponent_win = cwp(position ^ mask, mask)
    forced = possible & opponent_win
    if forced:
        if forced & (forced - 1):
            return 0
        possible = forced
    return possible & ~(opponent_win >> 1)


def negamax(position, mask, moves, alpha, beta, depth_tag="root"):
    global NODES
    NODES += 1
    possible = possible_non_losing(position, mask)
    if not possible:
        val = -((TOTAL - moves) // 2)
        if TRACE:
            print("  " * depth_tag if isinstance(depth_tag, int) else "", end="")
        return val
    if moves >= TOTAL - 2:
        return 0
    lo = -((TOTAL - 2 - moves) // 2)
    if alpha < lo:
        alpha = lo
        if alpha >= beta:
            return alpha
    hi = (TOTAL - 1 - moves) // 2
    if beta > hi:
        beta = hi
        if alpha >= beta:
            return beta

    list_moves = []
    for i in range(WIDTH):
        col = COLUMN_ORDER[i]
        mb = possible & BOTTOM_COL[col]
        if mb:
            mscore = bin(cwp(position | mb, mask | mb)).count("1")
            list_moves.append((mscore, col))
    list_moves.sort(key=lambda t: -t[0])

    values = []
    best = alpha
    first = True
    for _, col in list_moves:
        mb = possible & BOTTOM_COL[col]
        cpos = position ^ mask
        cmask = mask | mb
        if first:
            s = -negamax(cpos, cmask, moves + 1, -beta, -alpha)
            first = False
        else:
            s = -negamax(cpos, cmask, moves + 1, -alpha - 1, -alpha)
            if s > alpha:
                s = -negamax(cpos, cmask, moves + 1, -beta, -alpha)
        values.append((col, s))
        if s >= beta:
            return s
        if s > alpha:
            alpha = s
    return alpha


def full_window(seq):
    """ emulate solve(): canWinNext + bisection, contra Pons"""
    p, m, mv = load_position(seq)
    if can_win_next(p, m):
        return (TOTAL + 1 - mv) // 2
    lo_v = -((TOTAL - mv) // 2)
    hi_v = (TOTAL + 1 - mv) // 2
    while lo_v < hi_v:
        med = lo_v + (hi_v - lo_v) // 2
        if med <= 0:
            half = lo_v // 2 if lo_v >= 0 or lo_v % 2 == 0 else lo_v // 2 + 1
            if half < med:
                med = half
        else:
            half = hi_v // 2
            if half > med:
                med = half
        r = negamax(p, m, mv, med, med + 1)
        if r <= med:
            hi_v = r
        else:
            lo_v = r
    return lo_v


def main():
    print("проверка зеркала на известных: empty=", full_window(""), " '4'=", full_window("4"),
          " '1122334'=", full_window("1122334"))
    seed = "7422341735647741166133573473242566"
    print("зеркало на родителе:", full_window(seed), "(истина 1)")
    for c in (1, 2, 5, 6):
        seq = seed + str(c)
        cols, moves, mover = build_cols(seq)
        truth = solve_slow(cols, moves, mover=mover)
        got = full_window(seq)
        print(f"  +{c}: зеркало={got:3d} истина={truth:3d} {'OK' if got == truth else '!!!'}")


if __name__ == "__main__":
    main()
