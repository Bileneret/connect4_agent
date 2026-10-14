"""Побитовый разбор одного расходящегося случая cwp: формула vs брутфорс."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import random

sys.path.insert(0, str(ROOT))

import numpy as np
from engine.bitboard import compute_winning_position

sys.path.insert(0, str(ROOT / "tests"))
from debug_fuzz import random_playout, cwp_bruteforce_fast, py_cwp, decode  # noqa: E402

WIDTH, HEIGHT, H1 = 7, 6, 7
BOTTOM = sum(1 << (c * H1) for c in range(WIDTH))
BOARD = BOTTOM * ((1 << HEIGHT) - 1)


def cell_owner_map(position, mask):
    lines = []
    for r in range(HEIGHT - 1, -1, -1):
        row = ""
        for c in range(WIDTH):
            bit = 1 << (c * H1 + r)
            if mask >> bit_index(bit) & 1:
                row += "X" if position >> bit_index(bit) & 1 else "O"
            else:
                row += "."
        lines.append(f"  row{r} {row}")
    return "\n".join(lines)


def bit_index(bit):
    return bit.bit_length() - 1


def main():
    random.seed(7)
    bad_case = None
    for _ in range(600):
        pos, mask = random_playout(random.randint(4, 40))
        a = py_cwp(pos, mask)
        b = cwp_bruteforce_fast(pos, mask)
        if a != b:
            bad_case = (pos, mask, a, b)
            break

    pos, mask, a, b = bad_case
    print("mask  биты:", [i for i in range(49) if mask >> i & 1])
    print("pos   биты:", [i for i in range(49) if pos >> i & 1])
    print("доска (X=owner позиции, O=соперник, .=пусто):")
    print(cell_owner_map(pos, mask))
    print("cwp формула     :", decode(a), hex(a))
    print("cwp брутфорс    :", decode(b), hex(b))
    extra = b & ~a
    miss = a & ~b
    print("брутфорс находить дополнительно (формула пропускает):", decode(extra))
    print("формула лишнее:", decode(miss))
    for bit in decode(extra):
        c, r = bit
        print(f"--- разбор клетки {c},{r} ---")
        # проверить наличие 3 камней owner рядом, завершающих четверку
        for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
            for k in (-3, -2, -1, 0, 1, 2, 3):
                cells = [(c - dc * (k - i), r - dr * (k - i)) for i in range(4) if i != k]
                cells = [(col, row) for (col, row) in cells if 0 <= col < WIDTH and 0 <= row < HEIGHT]
                if len(cells) == 3 and all(pos >> (col * H1 + row) & 1 for col, row in cells):
                    print(f"   направлен. ({dc},{dr}): 3 камня owner: {cells} + наша {c},{r}")


if __name__ == "__main__":
    main()
