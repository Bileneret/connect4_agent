"""Офлайн-тесты игрового цикла (Этап 6/7): каскад решений, экстренный ход,
клик-верификация с фейковой страницей (физическая мышь НЕ используется).
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.dom_reader import BoardSnapshot  # noqa: E402
from engine.bitboard import load_position  # noqa: E402
from engine.opening_book import OpeningBook  # noqa: E402
from engine.solver_numba import SolverEngine  # noqa: E402
from state.game_loop import GameLoop, choose_emergency, decide_move  # noqa: E402
from state.session_manager import SessionManager  # noqa: E402


class FakeBook:
    """Фейковая книга: known_children — точные известные оценки детей."""
    def __init__(self, answer=None, known=None):
        if known is None and answer is not None:
            known = [(c, 1 if c == answer else 0) for c in range(7)]
        self._known = known or []
        self.available = bool(self._known)
        self.answer = answer

    def known_children(self, position, mask, moves=0):
        return list(self._known)

    def best_move(self, position, mask, moves=0):
        return self.answer


class FakeMouse:
    def __init__(self):
        self.plans = []

    def plan_column_click(self, center, radius, start=None):
        self.plans.append((center, radius))
        return ("plan", center, radius)

    def click(self, plan, apply=True):
        assert apply is False, "тесты не должны двигать физический курсор"
        return plan


def bits_to_grid(position, mask, my_turn, h=6, w=7):
    grid = [[0] * w for _ in range(h)]
    p, m = int(position), int(mask)
    for r in range(h):
        for c in range(w):
            bit = 1 << (c * 7 + r)
            if m & bit:
                ours = bool(p & bit) if my_turn else not (p & bit)
                grid[r][c] = 1 if ours else 2
    return grid


def make_snap(position, mask, my_turn, moves, left="04:00"):
    grid = bits_to_grid(position, mask, my_turn)
    heights = []
    for c in range(7):
        k = 0
        while k < 6 and grid[k][c]:
            k += 1
        heights.append(k)
    return BoardSnapshot(
        grid=grid, heights=heights, moves=moves, my_turn=my_turn,
        active_side="left" if my_turn else "right",
        timers={"left": left, "right": "04:00"},
        col_centers_client=[(100 + 50 * i, 500) for i in range(7)],
        board_rect={"x": 80, "y": 200, "w": 350, "h": 300},
        dpr=1.0, screen_x=0, screen_y=0, chrome_top_px=80, covered=[False] * 7)


def test_decide_cascade():
    t0 = time.time()
    # книга решает мгновенно
    dec = decide_move(None, FakeBook(2), *load_position(""), t0 + 30)
    assert (dec.kind, dec.col) == ("book", 2)
    # тактическая победа (у ходящего есть немедленная четвёрка)
    p, m, mv = load_position("112233")
    dec = decide_move(None, FakeBook(None), p, m, mv, t0 + 30)
    assert dec.kind == "tactical_win" and dec.col == 3, dec
    # тактический блок (у соперника одна играбельная угроза)
    p, m, mv = load_position("443322")
    dec = decide_move(None, FakeBook(None), p, m, mv, t0 + 30)
    assert dec.kind in ("tactical_block", "tactical_win"), dec
    print("  decide: книга/победа/блок — OK")


def test_emergency_and_deadline():
    engine = SolverEngine(max_gb=0.05)
    p, m, mv = load_position("4")   # нейтральная позиция: ни победы, ни блока
    # дедлайн уже прошёл -> мгновенный экстренный ход
    dec = decide_move(engine, FakeBook(None), p, m, mv, time.time() - 1)
    assert dec.kind == "emergency" and 0 <= dec.col < 7, dec
    col = choose_emergency(p, m, mv)
    assert 0 <= col < 7
    print(f"  decide: дедлайн-экстренный ход col={col + 1} — OK")


def test_loop_click_verify():
    """Фейковая страница: первый клик «не срабатывает», второй — успешен.

    Верификация — по числу НАШИХ фишек: неудачный снимок без изменений,
    успешный — ровно на одну нашу фишку больше.
    """
    import copy
    p, m, mv = load_position("4433")
    snap1 = make_snap(p, m, True, mv)
    snap2_fail = copy.deepcopy(snap1)  # доска не изменилась
    snap2_ok = copy.deepcopy(snap1)    # наша фишка добавилась
    snap2_ok.grid[0][0] = 1
    snap2_ok.heights[0] = 1
    snap2_ok.moves = mv + 1

    reads = [snap1, snap2_fail, snap2_ok]
    def fake_read(page):
        return reads.pop(0) if reads else snap2_ok

    mouse = FakeMouse()
    session = SessionManager()
    loop = GameLoop(page=object(), engine=SolverEngine(max_gb=0.05), book=FakeBook(3),
                    session=session, mouse=mouse, read_fn=fake_read,
                    apply_clicks=False, think_cap_s=0.1, human_rhythm=False)
    result = loop.step()
    assert result == "clicked", result
    assert loop.stats["clicks"] == 2 and loop.stats["retries"] == 1, loop.stats
    assert len(mouse.plans) == 2 and mouse.plans[0][1] > 0
    print("  click-verify: повтор после неудачи -> успех, OK")


def test_loop_hint_mode():
    p, m, mv = load_position("4433")
    snap = make_snap(p, m, True, mv)
    loop = GameLoop(page=object(), engine=SolverEngine(max_gb=0.05), book=FakeBook(2),
                    session=SessionManager(), mouse=FakeMouse(),
                    read_fn=lambda page: snap, apply_clicks=False, mode="hint", human_rhythm=False)
    assert loop.step() == "hint" and loop.stats["clicks"] == 0
    print("  hint-режим: решение без кликов, OK")


def test_loop_resync_on_desync():
    p, m, mv = load_position("4433")
    snap = make_snap(p, m, True, mv)
    snap.heights[0] = 5  # искусственный рассинхрон высот
    loop = GameLoop(page=object(), engine=SolverEngine(max_gb=0.05), book=FakeBook(2),
                    session=SessionManager(), mouse=FakeMouse(),
                    read_fn=lambda page: snap, apply_clicks=False, human_rhythm=False)
    assert loop.step() == "resync", "рассинхрон высот должен давать ресинк"
    print("  рассинхрон высот -> ресинк, OK")


def test_tie_randomization():
    """Q36: среди равноценных лучших ходов выбор случайный, не один и тот же."""
    class TieBook:
        available = True
        def best_move(self, *a): return None
        def known_children(self, position, mask, moves=0):
            vals = {0: 5, 3: 5, 6: 3}
            return [(c, vals.get(c, 0)) for c in range(7)]
    p, m, mv = load_position("")
    picks = set()
    for _ in range(24):
        dec = decide_move(None, TieBook(), p, m, mv, time.time() + 30)
        assert dec.kind == "book" and dec.col in (0, 3), dec
        picks.add(dec.col)
    assert picks == {0, 3}, f"рандом не развёл равноценные ходы: {picks}"
    print("  рандомизация равных (Q36): оба лучших хода встречаются — OK")


def test_covered_wait():
    """Q7: перекрытый попапом центр колонки -> клика нет, ожидание."""
    p, m, mv = load_position("4433")
    snap = make_snap(p, m, True, mv)
    snap.covered = [True] * 7
    loop = GameLoop(page=object(), engine=SolverEngine(max_gb=0.05), book=FakeBook(2),
                    session=SessionManager(), mouse=FakeMouse(),
                    read_fn=lambda page: snap, apply_clicks=False, human_rhythm=False)
    assert loop.step() == "covered_wait", "покрытая колонка должна ставить на ожидание"
    assert loop.stats.get("clicks", 0) == 0
    print("  covered-попап (Q7): клик отложен — OK")


def main():
    test_decide_cascade()
    test_emergency_and_deadline()
    test_loop_click_verify()
    test_loop_hint_mode()
    test_loop_resync_on_desync()
    test_tie_randomization()
    test_covered_wait()
    print("ИГРОВОЙ ЦИКЛ — ОФЛАЙН: ВСЁ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
