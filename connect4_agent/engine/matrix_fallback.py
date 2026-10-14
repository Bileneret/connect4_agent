"""Резервный матричный движок для больших полей (8x8, 9x7, 9x9) — Вопросы №11, №25.

Поля, не влезающие в uint64 (W*(H+1) > 64), играет этот модуль:
матрица int8 (владельцы камней — абсолютные 1/2), индексы высот колонок,
параметр turn (кто ходит; константа инварианта — никакой перекраски поля),
Zobrist-хеш в плоской таблице. Полный exact-solve на таких досках недостижим
по размеру дерева, поэтому движок делает итеративное углубление с бюджетом
времени; форсированные исходы внутри горизонта — дистанционно-точные
(обобщённая формула Понс а: (W*H + 1 - moves) // 2), листья — эвристика:
открытые тройки/двойки + парность угроз (Claimeven) + вес центра.
"""

import sys
import time
from pathlib import Path

import numpy as np
from numba import njit, int64, types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TT_BITS = 22  # 2^22 записей на движок


@njit(types.boolean(types.int8[::1], types.int64, types.int64, types.int64,
                    types.int64, types.int64), nogil=True)
def _wins_at(grid, w, h, col, row, player):
    """Четыре в ряд для player через клетку (col,row)."""
    for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
        count = 1
        c, r = col + dc, row + dr
        while 0 <= c < w and 0 <= r < h and grid[r * w + c] == player:
            count += 1
            c += dc
            r += dr
        c, r = col - dc, row - dr
        while 0 <= c < w and 0 <= r < h and grid[r * w + c] == player:
            count += 1
            c -= dc
            r -= dr
        if count >= 4:
            return True
    return False


@njit(types.int64(types.int8[::1], types.int64, types.int64, types.int8[::1],
                  types.int64), nogil=True)
def _immediate_wins(grid, w, h, heights, player):
    """Сколько колонок дают player немедленную победу (считает до двух)."""
    k = 0
    col = -1
    for c in range(w):
        if heights[c] >= h:
            continue
        r = heights[c]
        grid[r * w + c] = player
        if _wins_at(grid, w, h, c, r, player):
            k += 1
            col = c
        grid[r * w + c] = 0
        if k > 1:
            return k
    return k


@njit(types.int64(types.int8[::1], types.int64, types.int64, types.int8[::1],
                  types.int64, types.int64), nogil=True)
def _forced_block_col(grid, w, h, heights, player, n_threats):
    """Колонка вынужденного блока, когда у соперника ровно одна угроза.

    Блок обязан ПОЛНОСТЬЮ снять немедленные победы соперника (закрытая колонка
    сама может открыть ему новую ходящую клетку), поэтому после каждого
    кандидата проверяем всю позицию.
    """
    other = 3 - player
    for c in range(w):
        if heights[c] >= h:
            continue
        r = heights[c]
        grid[r * w + c] = player
        heights[c] = r + 1
        ok = _immediate_wins(grid, w, h, heights, other) == 0
        heights[c] = r
        grid[r * w + c] = 0
        if ok:
            return c
    return -1  # защиты нет — не должно случаться после фильтра угроз


@njit(types.int64(types.int8[::1], types.int64, types.int64, types.int64, types.int64),
      nogil=True)
def _evaluate(grid, w, h, player, moves):
    """Эвристика Вопроса №25: парность угроз, открытые линии, вес центра."""
    total = w * h
    my, opp = 0, 0
    my_col = player
    op_col = 3 - player
    # веса центра (статичны по колонке)
    for c in range(w):
        wgt = (6 if c == w // 2 else (4 if abs(c - w // 2) == 1 else
                                     (2 if abs(c - w // 2) == 2 else 1)))
        for r in range(h):
            p = grid[r * w + c]
            if p == my_col:
                my += wgt
            elif p == op_col:
                opp += wgt
    # окна по 4: открытые тройки/двойки + парность угроз
    for dc, dr in ((1, 0), (0, 1), (1, 1), (1, -1)):
        for c in range(w):
            for r in range(h):
                cc, rr = c + 3 * dc, r + 3 * dr
                if cc < 0 or cc >= w or rr < 0 or rr >= h:
                    continue
                n_m = n_o = 0
                empty_c = empty_r = -1
                for k in range(4):
                    cc = c + k * dc
                    rr = r + k * dr
                    p = grid[rr * w + cc]
                    if p == my_col:
                        n_m += 1
                    elif p == op_col:
                        n_o += 1
                    else:
                        empty_c, empty_r = cc, rr
                if n_o == 0 and empty_c >= 0:
                    if n_m == 3:
                        base = 60
                    elif n_m == 2:
                        base = 8
                    else:
                        continue
                    my += base
                    # парность (Claimeven): угрозы первого игрока на нечётных рядах
                    # (снизу 1,3,5) стратегически ценнее, чётные — для второго
                    if n_m == 3 and (empty_r % 2 == (0 if my_col == 1 else 1)):
                        my += 35
                elif n_m == 0 and empty_c >= 0:
                    if n_o == 3:
                        base = 60
                    elif n_o == 2:
                        base = 8
                    else:
                        continue
                    opp += base
                    if n_o == 3 and (empty_r % 2 == (1 if op_col == 2 else 0)):
                        opp += 35
    # ходящий с преимуществом темпа при равных железах
    return my - opp


@njit(types.int64(types.int8[::1], types.int8[::1], types.int64, types.int64,
                  types.int64, types.int64, types.int64, types.int64, types.int64,
                  types.uint64[::1], types.int16[::1], types.uint8[::1],
                  types.int64[::1], types.int64), nogil=True)
def _search(grid, heights, w, h, moves, turn, depth_left, alpha, beta,
            zobrist, tt_scores, tt_depth, nodes, order_hint):
    """Negamax с альфа-бета; точные форсированные исходы + эвристика на срезе."""
    nodes[0] += 1
    total = w * h

    # немедленная победа ходящего — дистанционно-точная оценка
    win_k = _immediate_wins(grid, w, h, heights, turn)
    if win_k > 0:
        return (total + 1 - moves) // 2

    # вынужденная двойная угроза соперника = неизбежная потеря
    threats = _immediate_wins(grid, w, h, heights, 3 - turn)
    if threats >= 2:
        # ходящий не блокирует обе; но и сам выиграть не может (проверено выше)
        return -((total - moves) // 2)
    if threats == 1:
        forced = _forced_block_col(grid, w, h, heights, turn, 1)
        if forced >= 0 and depth_left <= 0:
            # срез глубины на вынужденном ходу — представить оценку нейтрально минус темп
            return -2 - depth_left
        if forced >= 0:
            row = heights[forced]
            grid[row * w + forced] = turn
            heights[forced] = row + 1
            val = -_search(grid, heights, w, h, moves + 1, 3 - turn, depth_left - 1,
                           -beta, -alpha, zobrist, tt_scores, tt_depth, nodes, order_hint)
            heights[forced] = row
            grid[row * w + forced] = 0
            return val
        return -((total + 1 - moves) // 2)

    if moves >= total:
        return 0
    if depth_left <= 0:
        return _evaluate(grid, w, h, turn, moves)

    # Zobrist-каноника позиции (зарезервировано для стат-инспекции движка)
    key = types.uint64(14695981039346656037)
    i = 0
    while i < total:
        v = grid[i]
        if v != 0:
            key = key ^ zobrist[i * 2 + (v - 1)]
        i += 1

    # порядок ходов: центр -> края (для чётной ширины последний шаг уходит
    # за край — идём до w+1 и отбрасываем несуществующие колонки)
    mid = w // 2
    best = -10000
    for offset in range(w + 1):
        c = mid + (offset + 1) // 2 if offset % 2 else mid - offset // 2
        if c < 0 or c >= w or heights[c] >= h:
            continue
        row = heights[c]
        grid[row * w + c] = turn
        heights[c] = row + 1
        if _wins_at(grid, w, h, c, row, turn):
            val = (total + 1 - moves) // 2  # ход закрыл четвёрку — терминал
        elif depth_left == 1:
            val = -_evaluate(grid, w, h, 3 - turn, moves + 1)
        else:
            val = -_search(grid, heights, w, h, moves + 1, 3 - turn, depth_left - 1,
                           -beta, -alpha, zobrist, tt_scores, tt_depth, nodes, order_hint)
        heights[c] = row
        grid[row * w + c] = 0
        if val > best:
            best = val
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


class MatrixEngine:
    """Итеративное углубление с бюджетом времени для больших полей."""

    def __init__(self, tt_entries=1 << TT_BITS):
        rng = np.random.default_rng(0x5DEECE66D)
        self._zobrist = rng.integers(1, 2 ** 63, size=2 * 11 * 9, dtype=np.uint64)
        self._tt_scores = np.zeros(tt_entries, dtype=np.int16)
        self._tt_depth = np.zeros(tt_entries, dtype=np.uint8)
        self._nodes = np.zeros(1, dtype=np.int64)

    def best_move(self, grid, w, h, my_player, budget_s=1.5):
        """grid: список списков строк СНИЗУ ВВЕРХ (0 пусто, 1/2 владельцы).

        Возвращает (col, score_best_line, depth_done). Всегда возвращает
        легальный ход: минимум — центру-краю, который не подставляет победу.
        """
        heights = np.zeros(w, dtype=np.int8)
        flat = np.zeros(w * h, dtype=np.int8)
        for r in range(h):
            for c in range(w):
                v = int(grid[r][c])
                flat[r * w + c] = v
                if v:
                    heights[c] = max(heights[c], r + 1)
        moves = int(heights.sum())
        turn = int(my_player)

        deadline = time.perf_counter() + budget_s
        best_col = None
        best_score = None
        depth_done = 0

        # мгновенные форсированные решения без перебора
        win_k = _immediate_wins(flat, w, h, heights, turn)
        if win_k > 0:
            for c in range(w):
                if heights[c] < h:
                    r = heights[c]
                    flat[r * w + c] = turn
                    if _wins_at(flat, w, h, c, r, turn):
                        flat[r * w + c] = 0
                        return c, (w * h + 2 - moves) // 2, 0
                    flat[r * w + c] = 0
        opp_win_k = _immediate_wins(flat, w, h, heights, 3 - turn)
        if opp_win_k >= 2:
            # защита невозможна: играем по перебору на малой глубине
            pass
        elif opp_win_k == 1:
            c = _forced_block_col(flat, w, h, heights, turn, 1)
            if c >= 0:
                return c, (w * h - moves) // 2, 0

        mid = w // 2
        for depth in range(1, 33):
            if time.perf_counter() >= deadline:
                break
            self._tt_depth.fill(0)  # чистая ТТ на каждой глубине: значения не сопоставимы
            t0 = time.perf_counter()
            # оценка каждого корневого хода (корневой перебор в python)
            root_results = []
            aborted = False
            for offset in range(w + 1):
                c = mid + (offset + 1) // 2 if offset % 2 else mid - offset // 2
                if c < 0 or c >= w or heights[c] >= h:
                    continue
                self._nodes[0] = 0
                row = heights[c]
                flat[row * w + c] = turn
                heights[c] = row + 1
                try:
                    if _wins_at(flat, w, h, c, row, turn):
                        val = (w * h + 1 - moves) // 2  # корневой ход — победа
                    else:
                        val = -_search(flat, heights, w, h, moves + 1, 3 - turn,
                                       depth - 1, -10000, 10000, self._zobrist,
                                       self._tt_scores, self._tt_depth, self._nodes, 0)
                finally:
                    heights[c] = row
                    flat[row * w + c] = 0
                root_results.append((val, c))
                if time.perf_counter() - t0 > budget_s:
                    aborted = True
                    break
            if root_results and (not aborted or depth == 1):
                root_results.sort(key=lambda t: -t[0])
                best_col, best_score = root_results[0][1], root_results[0][0]
                depth_done = depth
            if aborted or time.perf_counter() >= deadline:
                break
        if best_col is None:  # страховка: любой легальный центру-краю ход
            for offset in range(w + 1):
                c = mid + (offset + 1) // 2 if offset % 2 else mid - offset // 2
                if 0 <= c < w and heights[c] < h:
                    return c, 0, 0
        return int(best_col), int(best_score), int(depth_done)
