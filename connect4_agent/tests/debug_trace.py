"""Трассировка зеркала negamax на сбойном ребёнке: каждый кадр."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from debug_mirror import negamax, full_window, cwp, possible_non_losing  # noqa: E402
from debug_mirror import BOTTOM_COL, COLUMN_ORDER, BOARD, H1, WIDTH, TOTAL  # noqa: E402
from engine.bitboard import load_position  # noqa: E402

TRACE_LINES = []
LIMIT = 120


def traced_negamax(position, mask, moves, alpha, beta, callpath="R"):
    if len(TRACE_LINES) < LIMIT:
        pnl_bits = possible_non_losing(position, mask)
        cols = [c // H1 for c in range(49) if pnl_bits >> c & 1]
        TRACE_LINES.append((callpath, moves, alpha, beta, cols))
    else:
        return 999  # за пределами лимита — фиктивное значение (не должно случиться)
    # тело = аналог negamax из зеркала, с записью результата
    if not pnl_bits:
        val = -((TOTAL - moves) // 2)
        TRACE_LINES[-1] += (f"possible==0 -> {val}",)
        return val
    if moves >= TOTAL - 2:
        TRACE_LINES[-1] += ("draw->0",)
        return 0
    lo = -((TOTAL - 2 - moves) // 2)
    if alpha < lo:
        alpha = lo
        if alpha >= beta:
            TRACE_LINES[-1] += (f"clip-lo -> {alpha}",)
            return alpha
    hi = (TOTAL - 1 - moves) // 2
    if beta > hi:
        beta = hi
        if alpha >= beta:
            TRACE_LINES[-1] += (f"clip-hi -> {beta}",)
            return beta

    moves_list = []
    for i in range(WIDTH):
        col = COLUMN_ORDER[i]
        mb = pnl_bits & BOTTOM_COL[col]
        if mb:
            mscore = bin(cwp(position | mb, mask | mb)).count("1")
            moves_list.append((mscore, col))
    moves_list.sort(key=lambda t: -t[0])

    first = True
    for _, col in moves_list:
        mb = pnl_bits & BOTTOM_COL[col]
        cpos = position ^ mask
        cmask = mask | mb
        if first:
            s = -traced_negamax(cpos, cmask, moves + 1, -beta, -alpha, callpath + f">{col + 1}")
            first = False
        else:
            s = -traced_negamax(cpos, cmask, moves + 1, -alpha - 1, -alpha, callpath + f">{col + 1}")
            if s > alpha:
                s = -traced_negamax(cpos, cmask, moves + 1, -beta, -alpha, callpath + f">{col + 1}R")
        if s >= beta:
            TRACE_LINES[-1] += (f"col{col + 1}: {s} >= beta -> {s}",)
            return s
        if s > alpha:
            alpha = s
        TRACE_LINES[-1] += (f"col{col + 1}:{s}",)
    TRACE_LINES[-1] += (f"-> {alpha}",)
    return alpha


def main():
    seed = "7422341735647741166133573473242566"
    seq = seed + "1"
    p, m, mv = load_position(seq)
    print(f"кадр для {seq[-6:]} (35 камней):")
    r = traced_negamax(p, m, mv, -22, 23)
    for path, moves, alpha, beta, cols, *rest in TRACE_LINES[:LIMIT]:
        print(f"  [{path}] moves={moves} a={alpha:3d} b={beta:3d} pnl-cols={cols}")
        for note in rest:
            print(f"        {note}")
    print("возврат:", r)


if __name__ == "__main__":
    main()
