"""Офлайн-тесты Этапа 6: мышь (планы без движения курсора), хоткеи (без хуков),
сессии/раунды/дисконнект/ресинк, дедлайны 40с/4:00, дампы инцидентов.
"""

import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from actuator.hotkeys import HotkeyDispatcher  # noqa: E402
from actuator.mouse_controller import MouseController  # noqa: E402
from browser.dom_reader import BoardSnapshot  # noqa: E402
from config import HOVER_MAX_MS, HOVER_MIN_MS, MOVE_TIME_LIMIT_S  # noqa: E402
from state.incident_logger import dump_incident  # noqa: E402
from state.session_manager import SessionManager  # noqa: E402


def make_snap(grid, my_turn, moves, left="04:00", right="04:00"):
    heights = []
    for c in range(7):
        h = 0
        while h < 6 and grid[h][c]:
            h += 1
        heights.append(h)
    return BoardSnapshot(
        grid=grid, heights=heights, moves=moves, my_turn=my_turn,
        active_side="left" if my_turn else "right",
        timers={"left": left, "right": right},
        col_centers_client=[(100 + i * 50, 500) for i in range(7)],
        board_rect={"x": 80, "y": 200, "w": 400, "h": 340},
        dpr=1.0, screen_x=0, screen_y=0, chrome_top_px=80, covered=[False] * 7,
    )


def empty_grid():
    return [[0] * 7 for _ in range(6)]


def test_mouse():
    mc = MouseController(rng=random.Random(42))
    center, radius = (500.0, 400.0), 36.0
    plan = mc.plan_column_click(center, radius, start=(100.0, 100.0))
    import math
    jitter = math.hypot(*plan.jitter)
    assert jitter <= radius * 0.5 + 1e-6, f"сдвиг {jitter} вне радиуса"
    assert plan.points[0] == (100.0, 100.0)
    assert abs(plan.points[-1][0] - plan.target[0]) < 1e-6
    assert HOVER_MIN_MS <= plan.hover_ms <= HOVER_MAX_MS
    assert 40 <= plan.down_ms <= 75
    assert len(plan.points) >= 8
    # воспроизводимость при одном seed
    plan2 = MouseController(rng=random.Random(42)).plan_column_click(
        center, radius, start=(100.0, 100.0))
    assert plan.points == plan2.points and plan.jitter == plan2.jitter
    # сухой прогон не трогает курсор и не падает
    mc.click(plan, apply=False)
    print("  mouse: OK (гауссов сдвиг в круге, Безье от старта к цели, dry-run)")

def test_hotkeys():
    fired = []
    d = HotkeyDispatcher()
    d.bind("toggle_mode", lambda: fired.append("toggle"))
    d.bind("pause", lambda: fired.append("pause"))
    d.bind("resync", lambda: fired.append("resync"))
    d.bind("exit", lambda: fired.append("exit"))
    assert d.handle("F7") == "toggle_mode"
    assert d.handle("f8") == "pause"
    assert d.handle("F9") == "resync"
    assert d.handle("esc") == "exit"
    assert d.handle("F5") is None
    assert fired == ["toggle", "pause", "resync", "exit"]
    print("  hotkeys: OK (F7/F8/F9/Esc -> обработчики, без установки хуков)")


def test_session():
    sm = SessionManager()
    # 1) нет доски
    assert sm.update(None, now=0.0) == []
    # 2) появилась пустая доска (наш ход)
    ev = sm.update(make_snap(empty_grid(), True, 0), now=1.0)
    assert [e.kind for e in ev] == ["NEW_GAME"]
    # 3) ход соперника (камень 2 в колонке 3)
    g = empty_grid(); g[0][3] = 2
    ev = sm.update(make_snap(g, True, 1, left="03:58"), now=2.0)
    assert [e.kind for e in ev] == ["OPPONENT_MOVE"] and ev[0].detail["col"] == 3
    # 4) наш ход (камень 1 в колонке 4) — старт пер-ходового бюджета
    g[0][4] = 1
    ev = sm.update(make_snap(g, False, 2), now=3.0)
    assert [e.kind for e in ev] == ["OUR_MOVE"] and ev[0].detail["col"] == 4
    # 5) наш ход начался (my_turn True-> был False): дедлайн ограничен 40с
    sm.update(make_snap(g, True, 2, left="03:55"), now=4.0)
    assert sm.st.turn_started_ts == 4.0
    dl = sm.think_deadline(now=4.0)
    assert dl is not None and dl - 4.0 <= MOVE_TIME_LIMIT_S - 5.9
    # при малом общем запасе дедлайн ужимается
    sm.st.our_time_left_s = 10.0
    assert sm.think_deadline(now=4.0) - 4.0 <= 8.5
    # 6) новый раунд: поле очистилось
    ev = sm.update(make_snap(empty_grid(), False, 0), now=5.0)
    assert [e.kind for e in ev] == ["NEW_ROUND"] and sm.st.round_no == 2
    # 7) дисконнект: тишина > 45 с при не нашем ходу
    ev = sm.update(make_snap(empty_grid(), False, 0), now=70.0)
    assert [e.kind for e in ev] == ["DISCONNECT"]
    # 8) битборды корректны: наша позиция после ходов
    sm2 = SessionManager()
    sm2.update(make_snap(empty_grid(), True, 0), now=0)
    g = empty_grid(); g[0][3] = 2; g[0][4] = 1
    sm2.update(make_snap(g, True, 2), now=1)
    from browser.dom_reader import from_grid
    pos, mask, moves = from_grid(g, True)
    assert (sm2.st.position, sm2.st.mask, moves) == (int(pos), int(mask), 2)
    print("  session: OK (NEW_GAME/ходы/раунды/DISCONNECT/битборды/дедлайны)")


def test_persist_restore():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "session_state.json"
        sm = SessionManager(state_path=path)
        sm.update(make_snap(empty_grid(), True, 0), now=0)
        g = empty_grid(); g[0][3] = 2
        sm.update(make_snap(g, True, 1, left="03:40"), now=1)
        sm.persist()
        sm2 = SessionManager(state_path=path)
        assert sm2.restore()
        assert sm2.st.moves == sm.st.moves and sm2.st.position == sm.st.position
        assert sm2.st.mask == sm.st.mask and sm2.st.our_time_left_s == 220.0
    print("  session persist/restore: OK")


def test_incident_logger():
    with tempfile.TemporaryDirectory() as td:
        folder = dump_incident("sync_lost", {"moves": 12, "note": "тест"},
                               base_dir=Path(td))
        assert folder.is_dir()
        data = json.loads((folder / "dump.json").read_text(encoding="utf-8"))
        assert data["kind"] == "sync_lost" and data["moves"] == 12
    print("  incident_logger: OK (dump.json создаётся)")


def main():
    test_mouse()
    test_hotkeys()
    test_session()
    test_persist_restore()
    test_incident_logger()
    print("ЭТАП 6 — ОФЛАЙН-ЧАСТЬ: ВСЁ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
