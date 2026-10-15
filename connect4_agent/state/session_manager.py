"""Сессии, раунды, ресинк и лимиты времени — Вопросы №10, №13, №16, №45.

SessionManager кормится снимками BoardSnapshot с метками времени и выдаёт
события: NEW_GAME, NEW_ROUND (поле очистилось после ходов), OUR_MOVE /
OPPONENT_MOVE (по владельцу нового камня), GAME_OVER, DISCONNECT (таймеры и
ходы замерли > 45 с). Позиция хранится битбордами (position, mask, moves) и
пишется в session_state.json — восстановление после F5 с любого момента (Q45).

TimeGuard следит за лимитами papergames: 40 с на ход и 4:00 на партию;
think_deadline() всегда возвращает безопасный дедлайн «думать».

Чистая логика без DOM/браузера — полностью покрывается офлайн-тестами.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    DISCONNECT_IDLE_S, GAME_TIME_LIMIT_S, MOVE_TIME_LIMIT_S,
)

CLICK_MARGIN_S = 8.0   # запас на клик/верификацию/повторы ВНУТРИ лимита хода
# (6.0 не хватало: размышление могло занять весь бюджет до резерва, а на клик
#  и верификацию с повторами нужно до 3-6 с — серия ловила тайм-ауты)


@dataclass
class SessionEvent:
    kind: str
    detail: dict = field(default_factory=dict)

    def __repr__(self):
        return f"<{self.kind} {self.detail}>"


@dataclass
class SessionState:
    game_no: int = -1
    round_no: int = 0
    moves: int = 0
    position: int = 0
    mask: int = 0
    my_turn: bool = False
    board_present: bool = False
    our_time_left_s: float | None = None
    turn_started_ts: float | None = None
    last_change_ts: float | None = None
    disconnect_reported: bool = False
    moved_this_turn: bool = False   # мы уже сходили в этом ходу (щит от дубль-кликов)


def _parse_timer(text: str | None) -> float | None:
    """'03:58' -> 238.0 секунд."""
    if not text:
        return None
    try:
        mm, ss = text.strip().split(":")
        return int(mm) * 60 + int(ss)
    except ValueError:
        return None


def _grid_diff(old_grid, new_grid):
    """(col, row, owner) нового камня или None, если изменений не одно."""
    if old_grid is None or new_grid is None:
        return None
    found = None
    for r, row in enumerate(new_grid):
        for c, v in enumerate(row):
            old_v = old_grid[r][c] if r < len(old_grid) and c < len(old_grid[r]) else 0
            if v != old_v:
                if v and not old_v and found is None:
                    found = (c, r, v)
                else:
                    return None  # больше одного изменения — не разбираем
    return found


class SessionManager:
    """Отслеживает игры/раунды и даёт безопасные дедлайны раздумий."""

    def __init__(self, state_path: Path | None = None):
        self.st = SessionState()
        self.prev_grid = None
        self.state_path = state_path
        self.emergency_mode = False   # не хватило времени на точный расчёт

    # --- события -----------------------------------------------------------
    def update(self, snapshot, now: float | None = None) -> list[SessionEvent]:
        """snapshot: BoardSnapshot или None (доска отсутствует)."""
        now = time.time() if now is None else now
        events: list[SessionEvent] = []

        if snapshot is None or not getattr(snapshot, "grid", None):
            if self.st.board_present and self.st.moves > 0:
                events.append(SessionEvent("GAME_OVER", {"moves": self.st.moves}))
            self.st.board_present = False
            self.prev_grid = None
            return events

        snap = snapshot
        if not self.st.board_present:
            self.st.game_no += 1
            self.st.round_no = 1
            self.st.moves = 0
            self.prev_grid = None
            events.append(SessionEvent("NEW_GAME", {"game_no": self.st.game_no}))
        self.st.board_present = True

        # изменение поля
        if snap.moves != self.st.moves:
            change = _grid_diff(self.prev_grid, snap.grid)
            if snap.moves < self.st.moves and snap.moves <= 1:
                self.st.round_no += 1
                events.append(SessionEvent("NEW_ROUND", {"round_no": self.st.round_no,
                                                         "moves": snap.moves}))
            elif snap.moves == self.st.moves + 1 and change is not None:
                col, row, owner = change
                kind = "OUR_MOVE" if owner == 1 else "OPPONENT_MOVE"
                events.append(SessionEvent(kind, {"col": col, "row": row}))
            self.st.moves = snap.moves
            self.st.last_change_ts = now
            self.st.disconnect_reported = False

        # пер-ходовой бюджет: старт — когда ход ПЕРЕШЁЛ к нам. Основной сигнал —
        # событие OPPONENT_MOVE (фишка соперника уже видна; «фронт» my_turn ловить
        # не нужно — под нагрузкой цикл читает реже, окно пропускается, и дедлайн
        # «стекал» в 0). Резервно — фронт False->True (ресинки/восстановление).
        our_move_ev = any(e.kind == "OUR_MOVE" for e in events)
        opp_move_ev = any(e.kind == "OPPONENT_MOVE" for e in events)
        new_round_ev = any(e.kind in ("NEW_GAME", "NEW_ROUND") for e in events)
        if our_move_ev:
            self.st.turn_started_ts = None
            self.st.moved_this_turn = True
        elif opp_move_ev:
            self.st.moved_this_turn = False
            self.st.turn_started_ts = now        # ход соперника завершён => наш ход
        elif new_round_ev:
            self.st.moved_this_turn = False
            self.st.turn_started_ts = now if snap.my_turn else None
        elif snap.my_turn and not self.st.my_turn:
            self.st.turn_started_ts = now
        elif not snap.my_turn:
            self.st.turn_started_ts = None
        self.st.my_turn = snap.my_turn

        # снимок позиции (Q16: прямо из доски)
        from browser.dom_reader import from_grid
        pos, mask, moves = from_grid(snap.grid, snap.my_turn)
        self.st.position, self.st.mask = int(pos), int(mask)

        # таймеры и дисконнект (Q13). ВАЖНО: наш таймер — на НАШЕЙ стороне
        # (в матчмейкинге и гостем комнаты мы бываем справа — слева часы соперника)
        _side = getattr(snap, "my_side", "left")
        ours = _parse_timer(snap.timers.get("right" if _side == "right" else "left"))
        if ours is not None:
            if self.st.our_time_left_s != ours:
                self.st.last_change_ts = now
                self.st.disconnect_reported = False
            self.st.our_time_left_s = ours
        self.prev_grid = [list(r) for r in snap.grid]
        if (self.st.last_change_ts is not None
                and now - self.st.last_change_ts > DISCONNECT_IDLE_S
                and not self.st.disconnect_reported
                and not snap.my_turn):
            self.st.disconnect_reported = True
            events.append(SessionEvent("DISCONNECT", {"idle_s": round(now - self.st.last_change_ts)}))
        return events

    # --- лимиты времени ----------------------------------------------------
    def think_deadline(self, now: float | None = None) -> float | None:
        """Абсолютный дедлайн «думать» с двойным запасом (40 с и общий банк)."""
        now = time.time() if now is None else now
        deadlines = []
        if self.st.turn_started_ts is not None:
            deadlines.append(self.st.turn_started_ts + MOVE_TIME_LIMIT_S - CLICK_MARGIN_S)
        if self.st.our_time_left_s is not None:
            # тот же запас, что и в пер-ходовом лимите: к моменту клика должен
            # остаться реальный люфт на клик+верификацию (иначе тайм-аут)
            deadlines.append(now + max(2.0, self.st.our_time_left_s - CLICK_MARGIN_S))
        return min(deadlines) if deadlines else None

    def budget_left(self, now: float | None = None) -> float | None:
        d = self.think_deadline(now)
        now = time.time() if now is None else now
        return None if d is None else max(0.0, d - now)

    # --- персистентность (Q45) --------------------------------------------
    def persist(self):
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "game_no": self.st.game_no, "round_no": self.st.round_no,
            "moves": self.st.moves, "position": self.st.position, "mask": self.st.mask,
            "my_turn": self.st.my_turn, "our_time_left_s": self.st.our_time_left_s,
            "ts": time.time(),
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    def restore(self) -> bool:
        if not self.state_path or not self.state_path.is_file():
            return False
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        self.st.game_no = data.get("game_no", -1)
        self.st.round_no = data.get("round_no", 0)
        self.st.moves = data.get("moves", 0)
        self.st.position = data.get("position", 0)
        self.st.mask = data.get("mask", 0)
        self.st.our_time_left_s = data.get("our_time_left_s")
        return True
