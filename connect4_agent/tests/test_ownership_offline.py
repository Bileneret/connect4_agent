"""Офлайн-тест инварианта владения камней — ловим транзиентные мисриды чтения
(фишка в анимации падения, на миг классифицированная как наша)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.bitboard import grid_ownership_ok  # noqa: E402


def grid(ours_cells=(), theirs_cells=()):
    g = [[0] * 7 for _ in range(6)]
    for r, c in ours_cells:
        g[r][c] = 1
    for r, c in theirs_cells:
        g[r][c] = 2
    return g


def main():
    # пустая доска — валидна при чьём угодно ходе
    assert grid_ownership_ok(grid(), True) and grid_ownership_ok(grid(), False)
    # один камень соперника, наш ход (мы вторые) — ок
    assert grid_ownership_ok(grid(theirs_cells=[(0, 3)]), True)
    # МИСРИД: тот же камень прочитан как НАШ при нашем ходе → ловится
    assert not grid_ownership_ok(grid(ours_cells=[(0, 3)]), True)
    # тот же камень при ИХ ходе — легально (мы начинали и только что сходили)
    assert grid_ownership_ok(grid(ours_cells=[(0, 3)]), False)
    # разница 2 — невалидно в любой момент
    assert not grid_ownership_ok(grid(ours_cells=[(0, 0), (0, 1)]), True)
    assert not grid_ownership_ok(grid(theirs_cells=[(0, 0), (0, 1)]), True)
    # середина партии: 1 наш против 2 их при нашем ходе — легально
    assert grid_ownership_ok(grid(ours_cells=[(0, 0)],
                                  theirs_cells=[(0, 3), (1, 3)]), True)
    # 2 наших против 1 их при ИХ ходе — легально (мы начинали)
    assert grid_ownership_ok(grid(ours_cells=[(0, 0), (0, 1)],
                                  theirs_cells=[(0, 3)]), False)
    # 2 против 2 при нашем ходе — легально (мы начинали)
    assert grid_ownership_ok(grid(ours_cells=[(0, 0), (0, 1)],
                                  theirs_cells=[(0, 3), (1, 3)]), True)
    # 1 против 1 при нашем ходе — легально
    assert grid_ownership_ok(grid(ours_cells=[(0, 0)], theirs_cells=[(0, 3)]), True)
    print("ИНВАРИАНТ ВЛАДЕНИЯ — ОФЛАЙН: ВСЁ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
