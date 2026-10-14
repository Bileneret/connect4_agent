"""Таблица транспозиций: плоские SoA-массивы NumPy + доступ из @njit.

Запись занимает 11 байт (Вопросы №29, №30):
    keys      uint64 (8 Б) — полный ключ позиции position + mask;
    scores    int8   (1 Б) — оценка в диапазоне [-21..21];
    metas     uint8  (1 Б) — (bound << 4) | колонка лучшего хода;
    depths    uint8  (1 Б) — depth = 42 - moves; 0 означает "слот пуст".
Корзина из двух слотов (2b, 2b+1); замещение depth-preferred: глубокие записи
не затираются мелкими. Число корзин — ближайшее простое число не выше цели.
"""

import numpy as np
from numba import njit, uint64, types

_BOUND_SHIFT = 4
_COL_MASK4 = 7

BOUND_LOWER = 1   # в позиции есть ход не хуже score
BOUND_UPPER = 2   # все ходы позиции не лучше score

BYTES_PER_ENTRY = 11

_SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    for p in _SMALL_PRIMES:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in _SMALL_PRIMES:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def prime_below(n: int) -> int:
    """Наибольшее простое число, не превышающее n (нечётные кандидаты)."""
    if n <= 2:
        return 2
    if n % 2 == 0:
        n -= 1
    while n > 2 and not _is_prime(n):
        n -= 2
    return n


def allocate_transposition_table(max_gb=4.0, ram_fraction=0.40, min_mb=128):
    """Автоматический размер под доступную ОЗУ (Вопрос №34), с psutil."""
    avail = None
    try:
        import psutil
        avail = psutil.virtual_memory().available
    except Exception:
        pass
    budget = int(max_gb * 1024 ** 3)
    if avail is not None:
        budget = min(budget, int(avail * ram_fraction))
    budget = max(budget, int(min_mb * 1024 ** 2))
    pairs = prime_below(max(1024, budget // BYTES_PER_ENTRY // 2))
    n = 2 * pairs
    return {
        "keys": np.zeros(n, dtype=np.uint64),
        "scores": np.zeros(n, dtype=np.int8),
        "metas": np.zeros(n, dtype=np.uint8),
        "depths": np.zeros(n, dtype=np.uint8),
        "pairs": np.uint64(pairs),
        "entries": n,
        "bytes": n * BYTES_PER_ENTRY,
    }


@njit(
    types.Tuple((types.boolean, types.int64, types.int32, types.int32))(
        uint64[::1], types.int8[::1], types.uint8[::1], types.uint8[::1], uint64, uint64
    ),
    cache=True, nogil=True,
)
def tt_lookup(keys, scores, metas, depths, pairs, key):
    """(найдено, оценка, тип границы 1/2, лучшая колонка) либо (False, 0, 0, -1)."""
    b = key % pairs
    s0 = b + b
    s1 = s0 + np.uint64(1)
    for s in (s0, s1):
        if depths[s] != np.uint8(0) and keys[s] == key:
            m = np.int32(metas[s])
            return True, np.int64(scores[s]), m >> _BOUND_SHIFT, m & _COL_MASK4
    return False, np.int64(0), np.int32(0), np.int32(-1)


@njit(
    types.void(
        uint64[::1], types.int8[::1], types.uint8[::1], types.uint8[::1],
        uint64, uint64, types.int64, types.int32, types.int32, types.int32
    ),
    cache=True, nogil=True,
)
def tt_store(keys, scores, metas, depths, pairs, key, score, bound, best_col, depth):
    """Сохранить запись; depth-preferred замещение внутри корзины из 2 слотов."""
    b = key % pairs
    s0 = b + b
    s1 = s0 + np.uint64(1)
    if depths[s0] == np.uint8(0) or keys[s0] == key:
        s = s0
    elif depths[s1] == np.uint8(0) or keys[s1] == key:
        s = s1
    elif depth >= depths[s0]:
        s = s0
    elif depth >= depths[s1]:
        s = s1
    else:
        return  # обе записи корзины глубже текущей — не затираем
    keys[s] = key
    scores[s] = np.int8(score)
    metas[s] = np.uint8(((bound << _BOUND_SHIFT) | (best_col & _COL_MASK4)) & 0xFF)
    depths[s] = np.uint8(depth)
