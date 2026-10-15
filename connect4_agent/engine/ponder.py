"""Pondering (Вопросы №28, №32): предрасчёт ответов соперника во время его хода.

Схема: как только мы сходили, менеджер расставляет приоритеты возможным ответам
соперника (по силе позиции для соперника — сначала те, что нам дороже всего
заплатить) и запускает рабочих потоков на общих таблицах транспозиций
(lockless-записи — черновые состояния при гонках не принимаются). Когда соперник
сделал реальный ход: если точная оценка ветки уже получена — ответ мгновенный;
иначе все рабочие прерываются, и основной поток продолжает углублять ветку
реального хода с прогретым кэшем.

Потоки реально распараллелены: numba @njit(nogil=True) освобождает GIL.
"""

import os
import sys
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.bitboard import BOTTOM_MASK, BOARD_MASK, COLUMN_MASK, play_bit  # noqa: E402
from config import WIDTH  # noqa: E402


class PonderManager:
    """Многопоточный предрасчёт веток соперника на общем движке.

    engine — единственный SolverEngine на процесс: все потоки делят его ТТ
    (lockless-записи безопасны) и счётчик узлов. Буферы сортировки ходов —
    СВОИ у каждого потока: общие на одной глубине давали гонку (чужой список
    подставлял ход вне позиции, в т.ч. полную колонну) → negamax уходил в
    «фантомного ребёнка» и выдавал ложные оценки (баг серии 16:20).
    """

    def __init__(self, engine, workers=None):
        self.engine = engine
        self._workers = workers or 4
        self._threads = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._results = {}      # col -> точная оценка (с точки зрения соперника)
        self._active = []       # колонки, находящиеся в предрасчёте
        self._base = None       # (position, mask, moves) нашей позиции после хода
        self._gen = 0           # поколение запуска: старые воркеры обязаны выйти

    # --- публичный API ------------------------------------------------------
    @property
    def results(self):
        with self._lock:
            return dict(self._results)

    def get_result(self, col):
        """Точная оценка состояния (base + ход соперника в col) либо None."""
        with self._lock:
            return self._results.get(col)

    def start(self, position, mask, moves, priorities=None):
        """Запустить pondering: разбор всех ответов соперника.

        priorities — опциональная последовательность колонок от вероятнейших
        к менее вероятным (для будущей эвристики предсказания); базовая
        FIFO — просто все играбельные колонки в порядке пригодности.
        """
        self.stop()
        base = (np.uint64(position), np.uint64(mask), int(moves))
        self._base = base
        cols = self._playable(mask)
        if priorities:
            cols = [c for c in priorities if c in cols] + [c for c in cols if c not in priorities]
        with self._lock:
            self._results.clear()
            self._active = list(cols)
        self._gen += 1
        gen = self._gen
        self._stop.clear()
        per = max(1, len(cols) // max(1, self._workers) + (len(cols) % self._workers != 0))
        self._threads = []
        for i in range(0, len(cols), per):
            chunk = cols[i:i + per]
            t = threading.Thread(target=self._worker, args=(base, chunk, gen), daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout=1.0):
        """Прервать предрасчёт (воркеры выходят после текущего solve-вызова).

        ВАЖНО: флаг остановки НЕ снимается здесь — иначе «застрявшие» воркеры
        продолжают считать свои колонки минутами (гонка с основным потоком).
        Снимается флаг только в start() для нового поколения.
        """
        self._stop.set()
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads = []
        self._stop.clear()

    def notify_move(self, col):
        """Соперник сходил в col. Возвращает точную оценку новой позиции или None."""
        self.stop()
        with self._lock:
            res = self._results.get(col)
            self._active = []
        return res

    # --- внутреннее ---------------------------------------------------------
    def _playable(self, mask):
        playable = (int(mask) + int(BOTTOM_MASK)) & int(BOARD_MASK) & ~int(mask)
        return [c for c in range(WIDTH) if playable & int(COLUMN_MASK[c])]

    def _move_bit(self, mask, col):
        """Бит первой пустой клетки колонки col (possible несёт именно её)."""
        return (int(mask) + int(BOTTOM_MASK)) & int(BOARD_MASK) & int(COLUMN_MASK[col])

    def _worker(self, base, cols, gen):
        position, mask, moves = base
        scratch = self.engine.make_scratch()   # СВОЯ пара буферов сортировки:
        # иначе на одной глубине потоки перезаписывают списки ходов друг друга
        try:  # пониженный приоритет ОС: под нагрузкой воркеры уступают CPU
            # клику/верификации и браузеру (иначе CDP-раундтрипы растягиваются с
            # миллисекунд до ~0.6 с — найдено на живой серии)
            import ctypes
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), -1)  # BELOW_NORMAL
        except Exception:  # noqa: BLE001 — не Windows/нет прав: не критично
            pass
        for col in cols:
            if self._stop.is_set() or self._gen != gen:
                return
            b = self._move_bit(int(mask), col)
            if not b:
                continue
            cp, cm = play_bit(np.uint64(position), np.uint64(mask), np.uint64(b))
            try:
                score = self.engine.solve(cp, cm, moves + 1, scratch=scratch)
            except ValueError:
                continue
            with self._lock:
                if self._gen != gen:      # устаревший воркер не пишет в новые результаты
                    return
                self._results[col] = score
                if col in self._active:
                    self._active.remove(col)
