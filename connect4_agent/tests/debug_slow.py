"""Вторая независимая реализация (матрицы, без битбордов) + спуск по дереву
для локализации расхождения моего ядра с эталонными оценками."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from engine.bitboard import load_position
from engine.solver_numba import SolverEngine

HEIGHT, WIDTH = 6, 7


def wins_at(cols, c, row, owner):
    def at(cc, rr):
        if 0 <= cc < WIDTH and 0 <= rr < len(cols[cc]):
            return cols[cc][rr] == owner
        return False
    for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
        cnt = 1
        for s in (1, -1):
            cc, rr = c + dc * s, row + dr * s
            while at(cc, rr):
                cnt += 1
                cc += dc * s
                rr += dr * s
        if cnt >= 4:
            return True
    return False


def solve_slow(cols, moves, alpha=-100, beta=100, mover=0):
    best = -100
    opp = 1 - mover
    for c in range(WIDTH):
        st = cols[c]
        if len(st) >= HEIGHT:
            continue
        st.append(mover)
        if wins_at(cols, c, len(st) - 1, mover):
            sc = (43 - moves) // 2
        elif moves + 1 == 42:
            sc = 0
        else:
            sc = -solve_slow(cols, moves + 1, -beta, -alpha, opp)
        st.pop()
        if sc > best:
            best = sc
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def build_cols(seq):
    cols = [[] for _ in range(WIDTH)]
    mover = 0
    for ch in seq:
        c = int(ch) - 1
        if len(cols[c]) >= HEIGHT:
            raise ValueError("переполнение колонки")
        cols[c].append(mover)
        mover = 1 - mover
    return cols, len(seq), mover


def main():
    eng = SolverEngine(max_gb=0.05)
    paths = sorted((ROOT / "tests" / "data").glob("Test_L3_R*"))
    lines = paths[0].read_text().splitlines()

    print("--- МАТРИЧНЫЙ эталон против файла (первые 12 позиций) ---")
    slow_ok = 0
    for line in lines[:12]:
        seq, exp_s = line.rsplit(None, 1)
        cols, moves, mover = build_cols(seq)
        if moves >= 42:
            continue
        slow = solve_slow(cols, moves, mover=mover)
        exp = int(exp_s)
        mark = "OK " if slow == exp else "BAD"
        if slow == exp:
            slow_ok += 1
        print(f"{seq[:20]:20s} len={len(seq):2d}  file={exp:3d}  slow={slow:3d} [{mark}]", flush=True)
    print(f"матричный эталон точен на {slow_ok}/12")

    print("--- Спуск по дереву: позиция 2 (file=1, движок даёт -3) ---")
    seq2 = "7422341735647741166133573473242566"
    cols, moves, mover = build_cols(seq2)
    p, m, mv = load_position(seq2)
    mine = eng.solve(np.uint64(p), np.uint64(m), mv)
    print(f"pos: 37 ходов, file=1, движок={mine}, slow={solve_slow(cols, moves, mover=mover)}")
    print("дети (col 1..7): slow_perspective_родителя против движка:")
    for c in range(WIDTH):
        if len(cols[c]) >= HEIGHT:
            continue
        cols2 = [list(x) for x in cols]
        cols2[c].append(mover)
        slow_child = solve_slow(cols2, moves + 1, mover=1 - mover)   # с точки зрения соперника
        seq_child = seq2 + str(c + 1)
        pp, mm, mvv = load_position(seq_child)
        mine_child = eng.solve(np.uint64(pp), np.uint64(mm), mvv)
        # оценка родителя через этого ребёнка: -slow_child / -mine_child
        print(f"  col{c + 1}: slow_child={slow_child:3d} -> родитель {-slow_child:3d} | "
              f" движок_child={mine_child:3d} -> родитель {-mine_child:3d}", flush=True)


if __name__ == "__main__":
    main()
