"""Единый игровой цикл — Этапы 6/7: чтение -> решение -> клик -> верификация.

Политика хода жёстко укладывается в лимит papergames (40 с на ход):
  1. КНИГА (все дети в книге)              — мгновенно, точный ход;
  2. ТАКТИКА (немедленная победа / блок)   — мгновенно, точный ход;
  3. ТОЧНЫЙ РАСЧЁТ best_column в потоке    — ждём до think_deadline (бюджет ~28 с);
  4. ЭКСТРЕННЫЙ ход (макс. угроз среди не-проигрывающих) — никогда не зависаем.
Осиротевший поток расчёта продолжает греть общую ТТ (lockless-записи безопасны),
следующий ход получит тёплый кэш. Примечание: scratch-строки сортировки ходов
общие на движок — при параллельных поисках возможна порча порядка ходов
(только производительность, не корректность результата).

Клик — физический (actuator.MouseController): плавная Безье-траектория к
центру нижней ячейки колонки со сдвигом; верификация через CLICK_VERIFY_MS
(наша фишка появилась ИЛИ ход передан), до CLICK_MAX_RETRIES повторов (Q39).
Перед кликом сверка высот DOM с битбордом (Q40): расхождение => ресинк.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import ANIMATION_SETTLE_MS, CLICK_MAX_RETRIES, CLICK_VERIFY_MS  # noqa: E402
from engine.bitboard import (  # noqa: E402
    COLUMN_MASK, column_heights, compute_winning_position, possible_moves,
    possible_non_losing_moves, popcount64,
)

H1 = 7
MID_COL = 3


@dataclass
class Decision:
    kind: str
    col: int


def _col_of(bit: int) -> int:
    return (bit.bit_length() - 1) // H1


def _winning_cells(position, mask) -> int:
    return int(compute_winning_position(position, mask)) & int(possible_moves(mask))


def _opp_forced_cells(position, mask) -> int:
    opp_win = int(compute_winning_position(int(position) ^ int(mask), mask))
    return int(possible_moves(mask)) & opp_win


def choose_emergency(position, mask, moves=0) -> int:
    """Экстренный ход: максимум создаваемых угроз среди не-проигрывающих."""

    allowed = int(possible_non_losing_moves(position, mask))
    if allowed == 0:
        allowed = int(possible_moves(mask))
    base_pos, base_mask = int(position), int(mask)
    best_col, best_key = MID_COL, None
    for c in range(7):
        bit = allowed & int(COLUMN_MASK[c])
        if not bit:
            continue
        npos = base_pos ^ base_mask
        nmask = base_mask | bit
        threats = int(popcount64(compute_winning_position(np.uint64(npos), np.uint64(nmask))))
        key = (threats, -abs(c - MID_COL))
        if best_key is None or key > best_key:
            best_col, best_key = c, key
    return best_col


def decide_move(engine, book, position, mask, moves, deadline_ts,
                think_cap_s=20.0, log=print) -> Decision:
    """Решение хода по каскаду политик (см. модульный docstring)."""
    # 1) книга
    if book is not None and getattr(book, "available", False):
        bm = book.best_move(position, mask, moves)
        if bm is not None:
            return Decision("book", int(bm))
    # 2) тактика
    win = _winning_cells(position, mask)
    if win:
        return Decision("tactical_win", _col_of(win & -win))
    forced = _opp_forced_cells(position, mask)
    if forced and (forced & (forced - 1)) == 0:
        return Decision("tactical_block", _col_of(forced))
    # 3) точный расчёт в отдельном потоке с бюджетом
    box: dict = {}

    def work():
        try:
            col, score, _ = engine.best_column(position, mask, moves)
            box["r"] = (int(col), int(score))
        except Exception as exc:  # noqa: BLE001 — доносим любую ошибку расчёта
            box["err"] = exc

    th = threading.Thread(target=work, daemon=True)
    th.start()
    limit = min(deadline_ts, time.time() + think_cap_s)
    while time.time() < limit and "r" not in box and "err" not in box:
        time.sleep(0.05)
    if "r" in box:
        return Decision("exact", box["r"][0])
    # 3б) частичная книга: максимум среди ТОЧНЫХ известных детей
    if book is not None and getattr(book, "available", False):
        known = book.known_children(position, mask, moves)
        if known:
            col = max(known, key=lambda t: (t[1], -abs(t[0] - MID_COL)))[0]
            return Decision("book_partial", int(col))
    # 4) экстренный ход — не зависаем
    return Decision("emergency", choose_emergency(position, mask, moves))


class GameLoop:
    """Оркестратор: снимок -> событие -> решение -> физический клик -> проверка."""

    def __init__(self, page, engine, book, session, mouse,
                 read_fn=None, apply_clicks=True, mode="auto", log=print,
                 think_cap_s=20.0):
        if read_fn is None:
            from browser.dom_reader import read_papergames
            read_fn = read_papergames
        self.page = page
        self.engine = engine
        self.book = book
        self.session = session
        self.mouse = mouse
        self.read_fn = read_fn
        self.apply_clicks = apply_clicks
        self.mode = mode            # "auto" | "hint"
        self.paused = False
        self.running = True
        self.think_cap_s = think_cap_s
        self.log = log
        self.last_opponent_move_ts = 0.0
        self.failures = 0
        self.browser_hwnd = None
        self.last_continue_ts = 0.0
        self.stats = {"book": 0, "tactical_win": 0, "tactical_block": 0,
                      "exact": 0, "emergency": 0, "clicks": 0, "retries": 0}

    # --- один тик -----------------------------------------------------------
    _CONTINUE_JS = r"""
    () => {
      const inRoom = /\/r\//.test(location.href);
      const rx = /^(continue|продолжить)$/i;
      const btn = Array.from(document.querySelectorAll('button'))
          .find(b => b.getBoundingClientRect().width > 0 && rx.test((b.textContent || '').trim()));
      if (!btn) return {clicked: false, inRoom};
      btn.click();
      return {clicked: true, inRoom, text: (btn.textContent || '').trim()};
    }
    """

    def _maybe_continue_round(self):
        """Q10: авто-продолжение серии раундов; после МАТЧА (лобби) — ничего не жмём (Q12)."""
        if time.time() - self.last_continue_ts < 3.0:
            return
        try:
            res = self.page.evaluate(self._CONTINUE_JS)
        except Exception:  # noqa: BLE001 — модал может исчезнуть между чтением и кликом
            return
        if res.get("clicked"):
            self.last_continue_ts = time.time()
            self.log(f"[loop] раунд-модал: нажал «{res.get('text')}» "
                     f"(в комнате: {res.get('inRoom')}) — продолжаем серию")

    def step(self) -> str | None:
        snap = self.read_fn(self.page)
        if snap is None or not snap.grid:
            if self.session.st.board_present and self.session.st.moves > 0:
                self.session.update(None, now=time.time())  # GAME_OVER
                self.persist()
                self.log("[loop] раунд/матч завершён — проверяю модал продолжения")
            self._maybe_continue_round()
            return None
        events = self.session.update(snap)
        for e in events:
            self.log(f"[loop] событие: {e}")
            if e.kind == "OPPONENT_MOVE":
                self.last_opponent_move_ts = time.time()
            if e.kind in ("NEW_ROUND", "NEW_GAME", "GAME_OVER", "DISCONNECT"):
                self.persist()
        if self.paused or not snap.my_turn:
            return None

        # Q4: не кликать раньше 500 мс после появления фишки соперника
        if self.last_opponent_move_ts:
            wait = ANIMATION_SETTLE_MS / 1000.0 - (time.time() - self.last_opponent_move_ts)
            if wait > 0:
                time.sleep(wait)

        # Q40: сверка высот DOM с битбордом перед решением и кликом
        position, mask = self.session.st.position, self.session.st.mask
        if snap.heights != column_heights(mask):
            self.log(f"[loop] РАССИНХРОН высот: dom={snap.heights} "
                     f"eng={column_heights(mask)} -> ресинк из DOM")
            return "resync"

        deadline = self.session.think_deadline() or (time.time() + self.think_cap_s)
        left = max(0.0, deadline - time.time())
        self.log(f"[loop] наш ход (moves={snap.moves}, бюджет {left:.1f} c)")
        dec = decide_move(self.engine, self.book, position, mask, snap.moves,
                          deadline, think_cap_s=self.think_cap_s, log=self.log)
        self.stats[dec.kind] = self.stats.get(dec.kind, 0) + 1
        self.log(f"[loop] решение: {dec.kind}, колонка {dec.col + 1}")
        self.persist()
        if self.mode == "hint":
            return "hint"
        if snap.heights[dec.col] >= 6:
            self.log("[loop] колонка полна — ресинк")
            return "resync"
        ok = self._click_and_verify(dec.col, snap)
        if ok:
            self.failures = 0
            self.persist()
            return "clicked"
        self.failures += 1
        if self.failures >= 2:
            self.paused = True
            self.log("[loop] две неудачи подряд — пауза (F8 для продолжения)")
        return "click_failed"

    # --- клик и верификация -------------------------------------------------
    def _ensure_click_target(self, x: float, y: float) -> bool:
        """Q38: поднять окно браузера и убедиться, что точка клика принадлежит ему."""
        from actuator.mouse_controller import (
            ensure_foreground, find_browser_window, top_level_at,
        )
        if self.browser_hwnd is None:
            self.browser_hwnd = find_browser_window()
        if not self.browser_hwnd:
            return True  # окно не нашли — не блокируем (best effort)
        ensure_foreground(self.browser_hwnd)
        time.sleep(0.12)
        at = top_level_at(int(x), int(y))
        if at != self.browser_hwnd:
            self.log("[loop] точка клика перекрыта другим окном (Q38), поднимаю браузер")
            ensure_foreground(self.browser_hwnd)
            time.sleep(0.2)
            at = top_level_at(int(x), int(y))
            if at != self.browser_hwnd:
                return False
        return True

    def _click_and_verify(self, col: int, snap) -> bool:
        radius_phys = (snap.board_rect["w"] / 7 / 2) * snap.dpr
        waits = (CLICK_VERIFY_MS / 1000.0, 1.2, 1.2)  # анимация фишки дорисуется не сразу
        t_start = time.time()
        for attempt in range(1 + CLICK_MAX_RETRIES):
            cx, cy = snap.col_center_screen_px(col)
            if self.apply_clicks and not self._ensure_click_target(cx, cy):
                self.log("[loop] окно браузера не поднимается наверх — пауза")
                self.paused = True
                return False
            if attempt:
                self.stats["retries"] += 1
                self.log(f"[loop] повторный клик (попытка {attempt + 1})")
            plan = self.mouse.plan_column_click((cx, cy), radius_phys)
            try:
                self.mouse.click(plan, apply=self.apply_clicks)
            except Exception as exc:  # noqa: BLE001 — FailSafe/ошибки ввода
                self.paused = True
                self.log(f"[loop] FAILSAFE/ошибка мыши: {exc} — пауза")
                return False
            self.stats["clicks"] += 1
            time.sleep(waits[min(attempt, len(waits) - 1)])
            snap2 = self.read_fn(self.page)
            if snap2 and snap2.grid and (snap2.moves == snap.moves + 1
                                         or not snap2.my_turn):
                self.log(f"[loop] клик подтверждён за {time.time() - t_start:.1f} с "
                         f"(попытка {attempt + 1})")
                return True
        self.log(f"[loop] клик не подтверждён после повторов "
                 f"({time.time() - t_start:.1f} с)")
        return False

    def persist(self):
        try:
            self.session.persist()
        except Exception as exc:  # noqa: BLE001
            self.log(f"[loop] persist не удался: {exc}")


def run_forever(loop: GameLoop, tick_s: float = 0.25):
    loop.log("[loop] запущен. F7 — Auto/Hint, F8 — пауза, F9 — ресинк, Esc — выход. "
             "FAILSAFE: резкий увод курсора в угол ставит на паузу.")
    loop.paused_by_failures = False
    loop.paused_since = 0.0
    try:
        while loop.running:
            try:
                loop.step()
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001 — цикл не должен падать
                loop.log(f"[loop] ошибка шага: {type(exc).__name__}: {exc}")
                loop.failures += 1
                time.sleep(1.0)  # перезагрузки страниц/навигации не должны «съедать» счётчик
                if loop.failures >= 10 and not loop.paused:
                    loop.paused = True
                    loop.paused_by_failures = True
                    loop.paused_since = time.time()
            # самовосстановление: пауза от ошибок снимается сама через 30 с
            # (ручная пауза F8 остаётся «залипающей»)
            if (loop.paused and getattr(loop, "paused_by_failures", False)
                    and time.time() - loop.paused_since > 30):
                loop.paused = False
                loop.paused_by_failures = False
                loop.failures = 0
                loop.log("[loop] авто-снятие паузы после ошибок — продолжаю")
            time.sleep(tick_s)
    finally:
        loop.persist()
        loop.log(f"[loop] остановлен. Статистика: {loop.stats}")
