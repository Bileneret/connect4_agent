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

import random
import sys
import threading
import time
from dataclasses import dataclass, field
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
    scores: dict = field(default_factory=dict)   # col -> int | str (для оверлея)
    info: str = ""                                # телеметрия (напр. узлы/с)


def _playable_cols(mask) -> int:
    possible = int(possible_moves(mask))
    return sum(1 for c in range(7) if possible & int(COLUMN_MASK[c]))


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
                think_cap_s=20.0, log=print, rng=None) -> Decision:
    """Решение хода по каскаду политик (см. модульный docstring)."""
    rng = rng or random
    # 1) книга: если известны ВСЕ дети — выбор среди равноценных лучших (Q36)
    if book is not None and getattr(book, "available", False):
        known = book.known_children(position, mask, moves)
        n_play = _playable_cols(mask)
        scores_map = dict(known)
        if known and len(known) == n_play:
            top = max(v for _, v in known)
            cols = [c for c, v in known if v == top]
            return Decision("book", rng.choice(cols), scores=scores_map)
    # 2) тактика
    win = _winning_cells(position, mask)
    if win:
        cells = []
        w = win
        while w:
            b = w & -w
            w ^= b
            cells.append(_col_of(b))
        return Decision("tactical_win", rng.choice(cells),
                        scores={c: ("WIN" if c in cells else None) for c in range(7)},
                        info=f"немедленная победа, вариантов {len(cells)}")
    forced = _opp_forced_cells(position, mask)
    if forced and (forced & (forced - 1)) == 0:
        col = _col_of(forced)
        return Decision("tactical_block", col,
                        scores={c: ("BLOCK" if c == col else None) for c in range(7)})
    # 3) точный расчёт в отдельном потоке с бюджетом
    box: dict = {}

    def work():
        try:
            t0 = time.time()
            n0 = engine.nodes
            res = engine.best_column(position, mask, moves)  # (col, best, [(col,score)...])
            dt = max(1e-6, time.time() - t0)
            rate = (engine.nodes - n0) / dt / 1e6
            box["r"] = (int(res[0]), int(res[1]), res[2], rate)
        except Exception as exc:  # noqa: BLE001 — доносим любую ошибку расчёта
            box["err"] = exc

    th = threading.Thread(target=work, daemon=True)
    th.start()
    limit = min(deadline_ts, time.time() + think_cap_s)
    while time.time() < limit and "r" not in box and "err" not in box:
        time.sleep(0.05)
    if "r" in box:
        col, best, results, rate = box["r"]
        # Q36: случайный выбор среди строго равноценных лучших ходов
        top = max(v for _, v in results)
        cols = [c for c, v in results if v == top]
        chosen = rng.choice(cols) if cols else col
        return Decision("exact", int(chosen),
                        scores=dict(results),
                        info=f"точн. {rate:.1f} млн узл/с, равных лучших: {len(cols)}")
    # 3б) частичная книга: максимум среди ТОЧНЫХ известных детей
    if book is not None and getattr(book, "available", False):
        known = book.known_children(position, mask, moves)
        if known:
            top = max(v for _, v in known)
            cols = [c for c, v in known if v == top]
            return Decision("book_partial", int(rng.choice(cols)),
                            scores=dict(known))
    # 4) экстренный ход — не зависаем
    col = choose_emergency(position, mask, moves)
    return Decision("emergency", col,
                    scores={c: ("PANIC" if c == col else None) for c in range(7)})


class GameLoop:
    """Оркестратор: снимок -> событие -> решение -> физический клик -> проверка."""

    def __init__(self, page, engine, book, session, mouse,
                 read_fn=None, apply_clicks=True, mode="auto", log=print,
                 think_cap_s=20.0, ponder=None, human_rhythm=True,
                 browser_port=None):
        if read_fn is None:
            from browser.dom_reader import read_papergames
            read_fn = read_papergames
        self.browser_port = browser_port
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
        self.ponder = ponder
        self.human_rhythm = human_rhythm
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
            self._clear_overlay()  # вне партии оверлей не нужен
            self._maybe_continue_round()
            return None
        events = self.session.update(snap)
        for e in events:
            self.log(f"[loop] событие: {e}")
            if e.kind == "OPPONENT_MOVE":
                self.last_opponent_move_ts = time.time()
                if self.ponder is not None:
                    val = self.ponder.notify_move(e.detail["col"])
                    self.log("[ponder] ответ соперника: " + (
                        f"готовый расчёт {val}" if val is not None else "расчёта нет"))
            if e.kind == "OUR_MOVE" and self.ponder is not None:
                # старт предрасчёта его ответов на позиции ПОСЛЕ нашего хода
                self.ponder.start(self.session.st.position, self.session.st.mask,
                                  snap.moves)
                self.log("[ponder] фон: расчёт ответов соперника")
            if e.kind in ("NEW_ROUND", "NEW_GAME", "GAME_OVER", "DISCONNECT"):
                self.persist()
                if e.kind in ("GAME_OVER", "DISCONNECT") and self.ponder is not None:
                    self.ponder.stop()
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
            self._dump_incident("desync_heights",
                                {"dom": snap.heights, "eng": column_heights(mask)})
            return "resync"

        deadline = self.session.think_deadline() or (time.time() + self.think_cap_s)
        left = max(0.0, deadline - time.time())
        self.log(f"[loop] наш ход (moves={snap.moves}, бюджет {left:.1f} c)")
        dec = decide_move(self.engine, self.book, position, mask, snap.moves,
                          deadline, think_cap_s=self.think_cap_s, log=self.log)
        self.stats[dec.kind] = self.stats.get(dec.kind, 0) + 1
        self.log(f"[loop] решение: {dec.kind}, колонка {dec.col + 1}"
                 + (f" | {dec.info}" if dec.info else ""))
        self.persist()

        # Q44: оверлей оценок колонок над доской (в обоих режимах)
        self._show_overlay(snap, dec)

        if self.mode == "hint":
            return "hint"
        if snap.heights[dec.col] >= 6:
            self.log("[loop] колонка полна — ресинк")
            self._dump_incident("column_full", {"col": dec.col, "heights": snap.heights})
            return "resync"
        # Q7: доска перекрыта попапом — не кликаем, ждём закрытия человеком
        if snap.covered and snap.covered[dec.col]:
            self._log_throttled("covered", "[loop] центр колонки перекрыт попапом "
                                           "(Q7) — жду закрытия окна")
            return "covered_wait"
        # Q35: человеческий ритм — короткая пауза перед кликом, в бюджете
        self._human_pause(dec, deadline)
        ok = self._click_and_verify(dec.col, snap)
        if ok:
            self.failures = 0
            self.persist()
            return "clicked"
        self.failures += 1
        self._dump_incident("click_failed", {"col": dec.col, "stats": dict(self.stats),
                                             "heights": snap.heights,
                                             "my_turn": snap.my_turn})
        if self.failures >= 2:
            self.paused = True
            self.log("[loop] две неудачи подряд — пауза (F8 для продолжения)")
        return "click_failed"

    # --- клик и верификация -------------------------------------------------
    _FRESH_TARGET_JS = r"""
    (col) => {
      const cells = Array.from(document.querySelectorAll('.grid-item'));
      const inCol = cells.filter(c => {
        const m = String(c.className).match(/cell-\d+-(\d+)/);
        return m && (+m[1] - 1) === col;
      });
      if (!inCol.length) return null;
      const rc = el => el.getBoundingClientRect();
      const bottom = inCol.reduce((a, b) => rc(a).y > rc(b).y ? a : b);
      const r = rc(bottom);
      return {cx: r.x + r.width / 2, cy: r.y + r.height / 2, radius: r.width / 2,
              dpr: window.devicePixelRatio || 1,
              screen_x: window.screenX, screen_y: window.screenY,
              chrome_top: Math.max(0, window.outerHeight - window.innerHeight)};
    }
    """

    def _fresh_click_target(self, col: int):
        """Свежие координаты цели прямо перед кликом (реклама может сдвинуть вёрстку)."""
        try:
            res = self.page.evaluate(self._FRESH_TARGET_JS, col)
        except Exception:  # noqa: BLE001
            return None
        return res if (res and "cx" in res) else None

    def _clear_overlay(self):
        """Убрать оверлей вне партии (после матча/раунда)."""
        try:
            from browser import overlay
            overlay.clear(self.page)
        except Exception:  # noqa: BLE001
            pass

    def _ensure_click_target(self, x: float, y: float) -> bool:
        """Q38: поднять окно браузера и убедиться, что точка клика принадлежит ему."""
        from actuator.mouse_controller import (
            ensure_foreground, find_browser_window, find_browser_window_for_port,
            top_level_at,
        )
        if self.browser_hwnd is None:
            # детерминированно по порту отладки (окна браузеров могут быть похожи)
            if self.browser_port:
                self.browser_hwnd = find_browser_window_for_port(self.browser_port)
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
            # свежие координаты: если реклама/баннер сдвинули вёрстку после снимка —
            # кликаем по фактическому положению клетки в момент клика
            fresh = self._fresh_click_target(col) if self.apply_clicks else None
            if fresh is not None:
                cx = (fresh["screen_x"] + fresh["cx"]) * fresh["dpr"]
                cy = (fresh["screen_y"] + fresh["chrome_top"] + fresh["cy"]) * fresh["dpr"]
                radius_phys = fresh["radius"] * fresh["dpr"]
            else:
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

    # --- вспомогательные живого режима -------------------------------------
    def _log_throttled(self, key: str, msg: str, interval: float = 30.0):
        now = time.time()
        if not hasattr(self, "_throttle"):
            self._throttle = {}
        if now - self._throttle.get(key, 0.0) > interval:
            self.log(msg)
            self._throttle[key] = now

    def _dump_incident(self, kind: str, payload: dict):
        """Q46: дамп сохраняется только при инцидентах (JSON + скриншот)."""
        try:
            from state.incident_logger import dump_incident
            folder = dump_incident(kind, payload, page=self.page)
            self.log(f"[loop] дамп инцидента сохранён: {folder.name}")
        except Exception as exc:  # noqa: BLE001 — дамп не должен ломать цикл
            self.log(f"[loop] дамп инцидента не удался: {exc}")

    def _show_overlay(self, snap, dec: Decision):
        """Q44: метки оценок колонок над доской (в Auto и Hint-режимах)."""
        if not getattr(snap, "board_rect", None):
            return
        try:
            from browser import overlay
            per_col = [dec.scores.get(c) if dec.scores else None for c in range(7)]
            overlay.inject(self.page, snap.board_rect, per_col, best_col=dec.col)
        except Exception as exc:  # noqa: BLE001 — оверлей не должен ломать игру
            self._log_throttled("overlay_err", f"[loop] оверлей не показан: {exc}")

    def _human_pause(self, dec: Decision, deadline: float):
        """Q35: коротко на вынужденных, вдумчиво в развилках — строго в бюджете."""
        if not self.human_rhythm:
            return
        from config import (CONSIDERED_COLUMNS_THRESHOLD, CONSIDERED_EXTRA_MS,
                            RAPID_EXTRA_MS)
        r = random.Random()
        known = [v for v in (dec.scores or {}).values() if isinstance(v, int)]
        if (dec.kind in ("tactical_win", "tactical_block")
                or len(known) < CONSIDERED_COLUMNS_THRESHOLD):
            extra = r.uniform(*RAPID_EXTRA_MS) / 1000.0
        else:
            extra = r.uniform(*CONSIDERED_EXTRA_MS) / 1000.0
        extra = max(0.0, min(extra, (deadline - time.time()) - 6.0))
        if extra > 0:
            self.log(f"[loop] человеческий ритм: пауза {extra:.2f} с")
            time.sleep(extra)


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
                if loop.failures < 3:  # Q46: первые сбои фиксируем дампом
                    loop._dump_incident("step_error", {"error": repr(exc)})
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
