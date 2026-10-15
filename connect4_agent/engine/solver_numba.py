"""Ядро поиска: Negamax + Alpha-Beta + PVS + фильтр non-losing moves.

Порт решателя Паскаля Понса (blog.gamesolver.org) на Numba @njit:
    * инвариант рекурсии — у ходящего игрока нет немедленного выигрыша
      (the root case обрабатывается отдельно, дети отсекаются фильтром);
    * окно поиска сужается теоретическими границами и границами из ТТ;
    * PVS: первый ход — полное окно, остальные — нулевое с возможным повтором;
    * порядок ходов: ТТ-ход -> приоритет центра -> число создаваемых угроз;
    * точный счёт позиции добывается нулевыми окнами (бисекция solve).
Инвариант по оценкам согласован с тестовыми наборами Понса (score 22-камней).
"""

import numpy as np
from numba import njit, uint64, types

from config import WIDTH, HEIGHT, TOTAL_CELLS
from engine.bitboard import (
    COLUMN_MASK, possible_moves, can_win_next,
    possible_non_losing_moves, compute_winning_position, popcount64, play_bit,
    load_position,
)
from engine.transposition_table import (
    allocate_transposition_table, tt_lookup, tt_store, BOUND_LOWER, BOUND_UPPER,
)

_COLUMN_ORDER = np.array([3, 2, 4, 1, 5, 0, 6], dtype=np.int64)
_U0 = np.uint64(0)
_MAX_MOVES = TOTAL_CELLS  # 42 — число строк scratch-буфера сортировки


@njit(
    types.int64(
        uint64, uint64, types.int64, types.int64, types.int64,
        types.uint64[::1], types.uint64[::1],
        uint64, types.int64[:, ::1], types.int8[:, ::1], types.int64[::1],
    ),
    cache=True, nogil=True,
)
def _negamax(position, mask, moves, alpha, beta,
             entry, check, pairs, sc_row, col_row, nodes):
    nodes[0] += 1

    # невозможность не проиграть ходом => соперник значит выигрывает следующим
    possible = possible_non_losing_moves(position, mask)
    if possible == _U0:
        return -((TOTAL_CELLS - moves) // 2)

    # двух остающихся камней уже не хватает на победу кому-либо
    if moves >= TOTAL_CELLS - 2:
        return 0

    # теоретические границы счёта (ниже/выше победить/выиграть нельзя)
    lo = -((TOTAL_CELLS - 2 - moves) // 2)
    if alpha < lo:
        alpha = lo
        if alpha >= beta:
            return alpha
    hi = (TOTAL_CELLS - 1 - moves) // 2
    if beta > hi:
        beta = hi
        if alpha >= beta:
            return beta

    key = position + mask
    found, tscore, tbound, tcol = tt_lookup(entry, check, pairs, key)
    if found:
        if tbound == BOUND_UPPER:
            if beta > tscore:
                beta = tscore
                if alpha >= beta:
                    return beta
        else:
            if alpha < tscore:
                alpha = tscore
                if alpha >= beta:
                    return alpha

    # генерация и сортировка ходов: центр -> края, по убыванию числа угроз
    n = 0
    for i in range(WIDTH):
        col = _COLUMN_ORDER[i]
        # possible содержит по одному биту — первую пустую клетку каждой
        # неполной колонки; выделяем её маской всей колонки
        move_bit = possible & COLUMN_MASK[col]
        if move_bit != _U0:
            mscore = np.int64(popcount64(compute_winning_position(position | move_bit, mask | move_bit)))
            k = n
            while k > 0 and sc_row[moves, k - 1] < mscore:
                sc_row[moves, k] = sc_row[moves, k - 1]
                col_row[moves, k] = col_row[moves, k - 1]
                k -= 1
            sc_row[moves, k] = mscore
            col_row[moves, k] = np.int8(col)
            n += 1

    best_col = tcol if found else np.int32(0)
    first = True
    for k in range(n):
        col = np.int64(col_row[moves, k])
        move_bit = possible & COLUMN_MASK[col]
        if move_bit == _U0:
            # повреждённый список ходов (гонка на ОБЩИХ буферах сортировки между
            # потоками: на той же глубине чужая позиция перезаписывает col_row) —
            # в невалидного ребёнка не уходим; nodes[1] — диагностический счётчик
            nodes[1] += 1
            continue
        cpos, cmask = play_bit(position, mask, move_bit)
        m_next = moves + 1
        if first:
            s = -_negamax(cpos, cmask, m_next, -beta, -alpha,
                          entry, check, pairs, sc_row, col_row, nodes)
            first = False
        else:
            s = -_negamax(cpos, cmask, m_next, -alpha - 1, -alpha,
                          entry, check, pairs, sc_row, col_row, nodes)
            if s > alpha:  # пробив нулевого окна — переискать с полным
                s = -_negamax(cpos, cmask, m_next, -beta, -alpha,
                              entry, check, pairs, sc_row, col_row, nodes)
        if s >= beta:
            tt_store(entry, check, pairs, key, s, BOUND_LOWER, col,
                     TOTAL_CELLS - moves)
            return s
        if s > alpha:
            alpha = s
            best_col = col

    tt_store(entry, check, pairs, key, alpha, BOUND_UPPER, best_col,
             TOTAL_CELLS - moves)
    return alpha


@njit(
    types.int64(
        uint64, uint64, types.int64,
        types.uint64[::1], types.uint64[::1],
        uint64, types.int64[:, ::1], types.int8[:, ::1], types.int64[::1],
    ),
    cache=True, nogil=True,
)
def _solve_root(position, mask, moves,
                entry, check, pairs, sc_row, col_row, nodes):
    if can_win_next(position, mask):
        return (TOTAL_CELLS + 1 - moves) // 2

    lo = -((TOTAL_CELLS - moves) // 2)
    hi = (TOTAL_CELLS + 1 - moves) // 2

    while lo < hi:
        med = lo + (hi - lo) // 2
        if med <= 0:
            half = lo // 2
            if lo < 0 and lo % 2 != 0:
                half += 1  # имитируем усечение C++ к нулю (как у Понса)
            if half < med:
                med = half
        else:
            half = hi // 2
            if half > med:
                med = half
        r = _negamax(position, mask, moves, med, med + 1,
                     entry, check, pairs, sc_row, col_row, nodes)
        if r <= med:
            hi = r
        else:
            lo = r
    return lo


class SolverEngine:
    """Python-обёртка: ТТ, буферы сортировки, счётчик узлов и API solve/best."""

    def __init__(self, max_gb=4.0, ram_fraction=0.40, min_mb=128):
        self.tt = allocate_transposition_table(max_gb, ram_fraction, min_mb)
        self._sc_row, self._col_row = self.make_scratch()
        self._nodes = np.zeros(2, dtype=np.int64)   # [0] узлы, [1] невалидные дети (диагн.)

    def make_scratch(self):
        """Своя пара буферов сортировки ходов для КАЖДОГО потока поиска.

        Общие буферы на одной глубине — гонка: чужой список ходов даёт ход вне
        своей позиции → невалидный ребёнок → ложные оценки (баг серии 16:20).
        """
        return (np.zeros((_MAX_MOVES, WIDTH), dtype=np.int64),
                np.zeros((_MAX_MOVES, WIDTH), dtype=np.int8))

    # --- служебное ---------------------------------------------------------
    @property
    def nodes(self):
        return int(self._nodes[0])

    @property
    def invalid_moves(self):
        """Счётчик невалидных детей (диагностика гонок сортировки); норма — 0."""
        return int(self._nodes[1])

    @property
    def tt_bytes(self):
        return self.tt["bytes"]

    def tt_fill(self):
        check = self.tt["check"]
        return int(np.count_nonzero(check)), check.shape[0]

    def reset_tt(self):
        self.tt["entry"].fill(0)
        self.tt["check"].fill(0)

    # --- публичный API ------------------------------------------------------
    def load_sequence(self, seq: str):
        """Строка ходов '1'..'7' -> (position, mask, moves)."""
        return load_position(seq)

    def solve(self, position, mask, moves=0, scratch=None) -> int:
        """Точная оценка позиции с точки зрения ходящего игрока.

        scratch — своя пара (sc_row, col_row) для параллельных потоков; без неё
        используется буфер движка (только для основного потока!).
        """
        sc, cr = scratch if scratch is not None else (self._sc_row, self._col_row)
        return int(_solve_root(position, mask, moves,
                               self.tt["entry"], self.tt["check"], self.tt["pairs"],
                               sc, cr, self._nodes))

    def solve_sequence(self, seq: str) -> int:
        position, mask, moves = self.load_sequence(seq)
        return self.solve(position, mask, moves)

    def best_column(self, position, mask, moves=0, scratch=None):
        """Точный лучший ход: оценка каждого ответа соперника полным решением.

        Возвращает (лучшая колонка 0..6, best_score, [(колонка, оценка) DESC]).
        """
        possible = int(possible_moves(mask))
        immediate_win = int(compute_winning_position(position, mask)) & possible
        win_score = (TOTAL_CELLS + 1 - moves) // 2
        results = []
        for c in range(WIDTH):
            bit = possible & int(COLUMN_MASK[c])
            if bit:
                if bit & immediate_win:
                    score = win_score
                else:
                    cpos, cmask = play_bit(position, mask, np.uint64(bit))
                    score = -self.solve(cpos, cmask, moves + 1, scratch=scratch)
                results.append((c, score))
        results.sort(key=lambda t: t[1], reverse=True)
        return results[0][0], results[0][1], results


def warmup(max_gb=0.05):
    """Прогрев/компиляция JIT (Вопрос №33): все ветки солвера за секунды."""
    eng = SolverEngine(max_gb=max_gb)
    eng.solve_sequence("4")        # бисекция + negamax + ТТ
    eng.solve_sequence("1122334")  # ветка немедленного выигрыша
    eng.solve_sequence("112233")   # соперник выигрывает немедленно
    return eng
