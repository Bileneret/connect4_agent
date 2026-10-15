"""Таблица транспозиций: lockless-записи, безопасные для Lazy SMP (Вопрос №32).

Каждый слот — пара uint64: entry (упакованные данные: score|bound|col|depth) и
check (key XOR entry). Пишем сначала data, потом check — читатель принимает
запись только если XOR совпал с полным ключом; порванное при гонке состояние
не может выглядеть валидным для чужого ключа (стандартный приём lockless
хеширования шахматных движков). Счёт смещён на +21 и хранится в 8 битах,
bound — 2 бита, колонка — 3 бита, depth (42 - moves) — 6 бит.

Корзина из двух слотов (2b, 2b+1), замещение depth-preferred; пустой слот
определяется check == 0. Число корзин — простое число (prime_below).
"""

import numpy as np
from numba import njit, uint64, types

BYTES_PER_ENTRY = 16  # entry + check

_BOUND_SHIFT = types.uint64(8)
_COL_SHIFT = types.uint64(10)
_DEPTH_SHIFT = types.uint64(14)
_SCORE_OFFSET = 21

BOUND_LOWER = 1
BOUND_UPPER = 2

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
    """Наибольшее простое число, не превышающее n."""
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
        "entry": np.zeros(n, dtype=np.uint64),
        "check": np.zeros(n, dtype=np.uint64),
        "pairs": np.uint64(pairs),
        "entries": n,
        "bytes": n * BYTES_PER_ENTRY,
    }


@njit(
    types.Tuple((types.boolean, types.int64, types.int32, types.int32))(
        types.uint64[::1], types.uint64[::1], uint64, uint64
    ),
    cache=True, nogil=True,
)
def tt_lookup(entry, check, pairs, key):
    """(найдено, оценка, тип границы 1/2, лучшая колонка) либо (False, 0, 0, -1)."""
    b = key % pairs
    s0 = b + b
    s1 = s0 + np.uint64(1)
    for s in (s0, s1):
        d = entry[s]
        if d != np.uint64(0) and (check[s] ^ d) == key:
            score = np.int64((d & np.uint64(0xFF)) - np.uint64(_SCORE_OFFSET))
            bound = np.int32((d >> _BOUND_SHIFT) & np.uint64(3))
            col = np.int32((d >> _COL_SHIFT) & np.uint64(7))
            return True, score, bound, col
    return False, np.int64(0), np.int32(0), np.int32(-1)


@njit(
    types.void(
        types.uint64[::1], types.uint64[::1], uint64, uint64,
        types.int64, types.int32, types.int32, types.int32
    ),
    cache=True, nogil=True,
)
def tt_store(entry, check, pairs, key, score, bound, best_col, depth):
    """Сохранить запись (data, key^data); depth-preferred замещение в корзине."""
    b = key % pairs
    s0 = b + b
    s1 = s0 + np.uint64(1)
    if check[s0] == np.uint64(0):
        s = s0
    elif check[s1] == np.uint64(0):
        s = s1
    else:
        d0 = (entry[s0] >> _DEPTH_SHIFT) & np.uint64(63)
        d1 = (entry[s1] >> _DEPTH_SHIFT) & np.uint64(63)
        if depth >= d0:
            s = s0
        elif depth >= d1:
            s = s1
        else:
            return  # обе записи корзины глубже текущей — не затираем
    data = (np.uint64(score + _SCORE_OFFSET) & np.uint64(0xFF)) \
        | (np.uint64(bound) << _BOUND_SHIFT) \
        | (np.uint64(best_col & 7) << _COL_SHIFT) \
        | (np.uint64(depth & 63) << _DEPTH_SHIFT)
    entry[s] = data
    check[s] = key ^ data
