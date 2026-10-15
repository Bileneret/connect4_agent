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
    # пустая доска — валидна
    assert grid_ownership_ok(grid(), True) and grid_ownership_ok(grid(), False)
    # один камень (чей угодно), наш ход — валидно (перевес в любую сторону)
    assert grid_ownership_ok(grid(theirs_cells=[(0, 3)]), True)
    assert grid_ownership_ok(grid(ours_cells=[(0, 3)]), True)
    assert grid_ownership_ok(grid(ours_cells=[(0, 3)]), False)
    # после нашего хода сайт переключает маркер с задержкой ~0.6-1 с:
    # «наших на один больше при нашем ходе» — это нормальный транзиент
    assert grid_ownership_ok(grid(ours_cells=[(0, 0), (0, 1)],
                                  theirs_cells=[(0, 3)]), True)
    # разница 2 — невалидно в любой момент
    assert not grid_ownership_ok(grid(ours_cells=[(0, 0), (0, 1)]), True)
    assert not grid_ownership_ok(grid(theirs_cells=[(0, 0), (0, 1)]), True)
    assert not grid_ownership_ok(grid(ours_cells=[(0, 0), (0, 1), (0, 2)],
                                      theirs_cells=[(0, 3)]), False)
    # середина партии: поровну/на один — всегда ок
    assert grid_ownership_ok(grid(ours_cells=[(0, 0)],
                                  theirs_cells=[(0, 3), (1, 3)]), True)
    assert grid_ownership_ok(grid(ours_cells=[(0, 0), (0, 1)],
                                  theirs_cells=[(0, 3), (1, 3)]), True)
    print("ИНВАРИАНТ ВЛАДЕНИЯ (баланс камней) — ОФЛАЙН: ВСЁ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
