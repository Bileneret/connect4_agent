"""Офлайн-тест хвоста «бюджет 0.0 c»: пер-ходовой бюджет обновляется по
событию OPPONENT_MOVE (надёжный сигнал), а не только по фронту my_turn
(под нагрузкой фронт пропускается — дедлайн «стекал» в 0 и каскад падал в
emergency). Плюс: наш таймер берётся с НАШЕЙ стороны (мы справа = timers.right).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.dom_reader import BoardSnapshot  # noqa: E402
from config import MOVE_TIME_LIMIT_S  # noqa: E402
from state.session_manager import CLICK_MARGIN_S, SessionManager  # noqa: E402

W, H = 7, 6


def snap(grid, my_turn, timers, my_side="left"):
    heights = [0] * W
    moves = 0
    for r in range(H):
        for c in range(W):
            if grid[r][c]:
                moves += 1
                heights[c] = r + 1
    return BoardSnapshot(
        grid=[list(r) for r in grid], heights=heights, moves=moves,
        my_turn=my_turn, active_side="left" if my_turn else "right",
        timers=timers, col_centers_client=[[0.0, 0.0]] * W,
        board_rect={"x": 0, "y": 0, "w": 0, "h": 0},
        dpr=1.0, screen_x=0, screen_y=0, chrome_top_px=0, covered=[False] * W,
        raw_errors=[], my_side=my_side)


def empty():
    return [[0] * W for _ in range(H)]


def with_discs(cols):
    """cols: колонки (0-based) по очереди: i-я фишка — наша (i чётное) / чужая."""
    g = empty()
    for i, c in enumerate(cols):
        r = 0
        while g[r][c]:
            r += 1
        g[r][c] = 1 if i % 2 == 0 else 2
    return g


def main():
    sm = SessionManager()
    t0 = 1000.0
    per_move = MOVE_TIME_LIMIT_S - CLICK_MARGIN_S

    # новая игра, наш ход (мы СПРАВА): бюджет стартует, таймер — наш (справа)
    ev = sm.update(snap(empty(), True, {"left": "04:00", "right": "03:00"}, "right"), now=t0)
    assert [e.kind for e in ev] == ["NEW_GAME"], ev
    assert sm.st.our_time_left_s == 180.0, sm.st.our_time_left_s  # 03:00 справа, НЕ 04:00
    d1 = sm.think_deadline(now=t0)
    assert abs(d1 - (t0 + per_move)) < 1e-6, d1
    print("  бюджет: старт на NEW_GAME (наш ход) + наш таймер справа — OK")

    # мы сходили — бюджет снят, взведён щит «уже сходили»
    ev = sm.update(snap(with_discs([3]), False, {"left": "04:00", "right": "02:58"}, "right"),
                   now=t0 + 5)
    assert [e.kind for e in ev] == ["OUR_MOVE"], ev
    assert sm.st.moved_this_turn is True
    assert sm.st.turn_started_ts is None
    print("  бюджет: OUR_MOVE снимает пер-ходовой бюджет, щит взведён — OK")

    # соперник сходил => наш ход: бюджет ОБЯЗАН обновиться с этого момента
    ev = sm.update(snap(with_discs([3, 5]), True, {"left": "03:58", "right": "02:58"}, "right"),
                   now=t0 + 12)
    assert [e.kind for e in ev] == ["OPPONENT_MOVE"], ev
    assert sm.st.moved_this_turn is False
    d2 = sm.think_deadline(now=t0 + 12)
    assert abs(d2 - (t0 + 12 + per_move)) < 1e-6, d2
    print("  бюджет: OPPONENT_MOVE обновляет дедлайн (без ловли фронта) — OK")

    # повторное чтение того же состояния не должно переставлять дедлайн
    sm.update(snap(with_discs([3, 5]), True, {"left": "03:58", "right": "02:52"}, "right"),
              now=t0 + 20)
    d3 = sm.think_deadline(now=t0 + 20)
    assert abs(d3 - d2) < 1e-6, (d2, d3)
    print("  бюджет: повторные чтения дедлайн не двигают — OK")

    print("ХВОСТ «бюджет 0.0 c» — ОФЛАЙН: ВСЁ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
