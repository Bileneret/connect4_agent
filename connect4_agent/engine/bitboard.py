"""Битовые структуры поля 7x6 — схема Паскаля Понса / Джона Тромпа.

Разметка: колонка c занимает биты [c*7 .. c*7+6] — 6 игровых рядов снизу вверх
плюс один сигнальный бит сверху (всегда 0, не даёт переносить биты между колонками).

Позиция кодируется парой (position, mask):
    position — битборд камней игрока, чья сейчас очередь хода;
    mask     — битборд всех камней на доске.
Ключ позиции для кэша: key = position + mask (однозначен).

Важно для Numba: все константы, смешивающиеся с uint64-величинами, заданы как
np.uint64 — numba при смешении знаковых и беззнаковых целых уходит в float64.
"""

import numpy as np
from numba import njit, uint64, int64, boolean
from numba import types

from config import WIDTH, HEIGHT

H1 = HEIGHT + 1                      # бит на колонку (7)
TOTAL_CELLS = WIDTH * HEIGHT         # 42

# --- Маски-константы -------------------------------------------------------
BOTTOM_MASK = np.uint64(sum(1 << (c * H1) for c in range(WIDTH)))
BOARD_MASK = np.uint64(int(BOTTOM_MASK) * ((1 << HEIGHT) - 1))
BOTTOM_COL = np.array([1 << (c * H1) for c in range(WIDTH)], dtype=np.uint64)
COLUMN_MASK = np.array([((1 << HEIGHT) - 1) << (c * H1) for c in range(WIDTH)], dtype=np.uint64)

_G1 = np.uint64(0x5555555555555555)
_G2 = np.uint64(0x3333333333333333)
_G4 = np.uint64(0x0F0F0F0F0F0F0F0F)
_G8 = np.uint64(0x0101010101010101)
_U0 = np.uint64(0)
_U1 = np.uint64(1)
_SH1 = np.uint64(H1)
_UR = np.uint64(H1 - 1)     # диагональ "вниз-вправо" (сдвиг 6)
_UL = np.uint64(H1 + 1)     # диагональ "вверх-вправо" (сдвиг 8)


@njit(uint64(uint64), cache=True, nogil=True)
def popcount64(x):
    """Число установленных битов (SWAR, без спец-инструкций)."""
    x = x - ((x >> _U1) & _G1)
    x = (x & _G2) + ((x >> np.uint64(2)) & _G2)
    x = (x + (x >> np.uint64(4))) & _G4
    return (x * _G8) >> np.uint64(56)


@njit(uint64(uint64), cache=True, nogil=True)
def possible_moves(mask):
    """По одной нижней пустой клетке каждой неполной колонки."""
    return (mask + BOTTOM_MASK) & BOARD_MASK


@njit(uint64(uint64, uint64), cache=True, nogil=True)
def compute_winning_position(position, mask):
    """Все пустые клетки, заняв которые игрок completes четырёхвряд (Понс)."""
    # вертикаль: клетка завершает четвёрку только над тремя фишками подряд
    r = (position << _U1) & (position << np.uint64(2)) & (position << np.uint64(3))

    # горизонталь (шаг 7)
    p = (position << _SH1) & (position << np.uint64(2 * H1))
    r |= p & (position << np.uint64(3 * H1))
    r |= p & (position >> _SH1)
    p = (position >> _SH1) & (position >> np.uint64(2 * H1))
    r |= p & (position << _SH1)
    r |= p & (position >> np.uint64(3 * H1))

    # диагональ D1 (шаг 6)
    p = (position << _UR) & (position << np.uint64(2 * (H1 - 1)))
    r |= p & (position << np.uint64(3 * (H1 - 1)))
    r |= p & (position >> _UR)
    p = (position >> _UR) & (position >> np.uint64(2 * (H1 - 1)))
    r |= p & (position << _UR)
    r |= p & (position >> np.uint64(3 * (H1 - 1)))

    # диагональ D2 (шаг 8)
    p = (position << _UL) & (position << np.uint64(2 * (H1 + 1)))
    r |= p & (position << np.uint64(3 * (H1 + 1)))
    r |= p & (position >> _UL)
    p = (position >> _UL) & (position >> np.uint64(2 * (H1 + 1)))
    r |= p & (position << _UL)
    r |= p & (position >> np.uint64(3 * (H1 + 1)))

    return r & (BOARD_MASK ^ mask)


@njit(boolean(uint64), cache=True, nogil=True)
def has_won(position):
    """Есть ли у игрока с битбордом position выстроенная четвёрка."""
    m = position & (position >> _SH1)
    if (m & (m >> np.uint64(2 * H1))) != _U0:
        return True
    m = position & (position >> _UR)
    if (m & (m >> np.uint64(2 * (H1 - 1)))) != _U0:
        return True
    m = position & (position >> _UL)
    if (m & (m >> np.uint64(2 * (H1 + 1)))) != _U0:
        return True
    m = position & (position >> _U1)
    if (m & (m >> np.uint64(2))) != _U0:
        return True
    return False


@njit(boolean(uint64, uint64), cache=True, nogil=True)
def can_win_next(position, mask):
    """Текущий игрок может выиграть немедленным ходом."""
    return (compute_winning_position(position, mask) & possible_moves(mask)) != _U0


@njit(uint64(uint64, uint64), cache=True, nogil=True)
def possible_non_losing_moves(position, mask):
    """Ходы, не отдающие сопернику победу следующим же ходом (Вопрос №24).

    1) если у соперника есть выигрышные клетки — блокировать; две одновременные
       угрозы не отбиваются вовсе (возврат 0);
    2) исключить ход, открывающий сопернику выигрышную клетку непосредственно
       над местом нашей фишки.
    """
    possible = possible_moves(mask)
    opponent_win = compute_winning_position(position ^ mask, mask)
    forced = possible & opponent_win
    if forced != _U0:
        if (forced & (forced - _U1)) != _U0:
            return _U0
        possible = forced
    return possible & ~(opponent_win >> _U1)


@njit(types.Tuple((uint64, uint64))(uint64, uint64, uint64), cache=True, nogil=True)
def play_bit(position, mask, move_bit):
    """Применить ход-бит; position после хода — камни нового игрока (соперника)."""
    return (position ^ mask, mask | move_bit)


@njit(types.Tuple((uint64, uint64))(uint64, uint64, int64), cache=True, nogil=True)
def play_column(position, mask, col):
    """Применить ход в колонку col (0..6). В неполную колонку — фишка в её дно."""
    move_bit = (mask + BOTTOM_COL[col]) & BOARD_MASK & ~mask
    return (position ^ mask, mask | move_bit)


@njit(uint64(uint64), cache=True, nogil=True)
def mirror_bitboard(b):
    """Зеркало слева-направо: колонки 0<->6, 1<->5, 2<->4 (Вопрос №26)."""
    col_m = np.uint64((1 << H1) - 1)
    res = _U0
    for c in range(WIDTH):
        col_bits = (b >> np.uint64(c * H1)) & col_m
        res |= col_bits << np.uint64((WIDTH - 1 - c) * H1)
    return res


def load_position(seq):
    """Строка ходов '1'..'7' -> (position, mask, moves). Активна для Python-кода.

    Арифметика — на Python-целых (numba возвращает uint64 как int, а numpy 2.x
    запрещает смешивать отрицательные Python int с uint64); в jitted play_bit
    значения передаются с явным np.uint64().
    """
    position = 0
    mask = 0
    moves = 0
    board = int(BOARD_MASK)
    for ch in seq:
        col = int(ch) - 1
        if not 0 <= col < WIDTH:
            raise ValueError(f"некорректная колонка {ch!r} в последовательности {seq!r}")
        move_bit = (mask + int(BOTTOM_COL[col])) & board & ~mask
        if move_bit == 0:
            raise ValueError(f"колонка {col + 1} переполнена в последовательности {seq!r}")
        position, mask = play_bit(np.uint64(position), np.uint64(mask), np.uint64(move_bit))
        moves += 1
    return position, mask, moves


def column_heights(mask):
    """Число фишек в каждой колонке (для сверки с DOM, Вопрос №40)."""
    m = int(mask)
    return [ (m & int(COLUMN_MASK[c])).bit_count() for c in range(WIDTH) ]
