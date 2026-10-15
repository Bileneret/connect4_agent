"""Дебютная книга: точные оценки канонических позиций первых N полуходов.

Файл книги (npz): keys uint64 (отсортированные канонические ключи), scores int8,
moves uint8. Канонический ключ = min(key, mirror_key) — орбита зеркальной
симметрии (Вопрос №26), одна оценка на две зеркальные позиции.

Рантайм (класс OpeningBook): оценка и выбор хода мгновенно, без вызова солвера.
Ход выбирается оценкой всех играбельных детей из книги; если хотя бы один ребёнок
отсутствует, возвращается None — эстафета переходит солверу (безопасный контракт).

Генератор (generate_book): DFS из пустой доски с канонической дедупликацией и
прогретой общей таблицей транспозиций; слои решаются от глубоких к мелким,
после каждого слоя — атомарный чекпоинт npz. Реалистично это фоновая работа
на часы/дни: каждая дебютная позиция — полный идеальный solve.
"""

import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.bitboard import BOARD_MASK, BOTTOM_MASK, mirror_bitboard, play_bit
from engine.solver_numba import SolverEngine

BOOK_DIR = Path(__file__).resolve().parents[1] / "books"
BOOK_FILE = BOOK_DIR / "opening_book.npz"


def canonical_key(position, mask):
    """Канонический ключ орбиты зеркальной симметрии (python-целые на входе)."""
    key = int(position) + int(mask)
    mkey = int(mirror_bitboard(np.uint64(position))) + int(mirror_bitboard(np.uint64(mask)))
    return key if key <= mkey else mkey


def enumerate_states(limit):
    """Все канонические позиции с числом камней <= limit.

    Возвращает список по слоям: layers[moves] = dict{canon_key: (position, mask)}.
    DFS из пустой доски; один стейт на зеркальную орбиту.
    """
    layers = [dict() for _ in range(limit + 1)]
    board = int(BOARD_MASK)

    def rec(position, mask, moves):
        if moves >= limit:
            return
        # по одной первой пустой клетке каждой неполной колонки (carry-трюк)
        possible = (int(mask) + int(BOTTOM_MASK)) & board
        while possible:
            b = possible & -possible
            possible ^= b
            cpos = int(position) ^ int(mask)   # камни соперника — новый ходящий
            cmask = int(mask) | b
            child_moves = moves + 1
            ck = canonical_key(cpos, cmask)
            layer = layers[child_moves]
            if ck not in layer:
                layer[ck] = (cpos, cmask)
                rec(cpos, cmask, child_moves)

    layers[0][canonical_key(0, 0)] = (0, 0)
    rec(0, 0, 0)
    return layers


def generate_book(limit, out_path=BOOK_FILE, max_gb=3.5, log_every=200):
    """Сгенерировать книгу точных оценок до depth limit (включительно).

    Слои решаются от глубоких к мелким — ТТ внутри слоя прогревается соседями,
    затем мелкие слои попадают в готовые границы. После каждого слоя — чекпоинт.
    """
    t_all = time.perf_counter()
    print(f"[book] перечисление состояний до depth {limit}...", flush=True)
    t0 = time.perf_counter()
    layers = enumerate_states(limit)
    total = sum(len(l) for l in layers)
    print(f"[book] состояний: {total} "
          + " ".join(f"d{d}:{len(layers[d])}" for d in range(limit + 1))
          + f" ({time.perf_counter() - t0:.1f} с)", flush=True)

    engine = SolverEngine(max_gb=max_gb)
    keys_all, scores_all, moves_all = [], [], []

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for depth in range(limit, -1, -1):
        states = layers[depth]
        t0 = time.perf_counter()
        done = 0
        for ck, (pos, mask) in states.items():
            t_state = time.perf_counter()
            score = engine.solve(np.uint64(pos), np.uint64(mask), depth)
            dt_state = time.perf_counter() - t_state
            keys_all.append(ck)
            scores_all.append(score)
            moves_all.append(depth)
            done += 1
            if log_every and done % log_every == 0:
                rate = done / max(1e-9, time.perf_counter() - t0)
                print(f"[book] depth {depth}: {done}/{len(states)} "
                      f"({rate:.1f} поз/с, TT {engine.tt_bytes / 1024 ** 3:.2f} ГБ)", flush=True)
            if dt_state > 20:
                print(f"[book]   тяжесть: depth {depth} key={ck} {dt_state:.1f} с "
                      f"({engine.nodes / 1e6:.0f} млн узлов суммарно)", flush=True)
        dt = time.perf_counter() - t0

        # чекпоинт после слоя
        keys = np.array(sorted(keys_all), dtype=np.uint64)
        scores_arr = np.zeros(len(keys), dtype=np.int8)
        moves_arr = np.zeros(len(keys), dtype=np.uint8)
        sdict = {}
        for k, s, m in zip(keys_all, scores_all, moves_all):
            sdict[k] = (s, m)
        for i, k in enumerate(keys):
            s, m = sdict[int(k)]
            scores_arr[i] = s
            moves_arr[i] = m
        tmp = out_path.parent / (out_path.stem + ".tmp.npz")
        np.savez_compressed(tmp, keys=keys, scores=scores_arr, moves=moves_arr)
        os.replace(tmp, out_path)
        print(f"[book] чекпоинт после depth {depth}: ключей {len(keys)}, "
              f"слой {dt:.0f} с, всего {time.perf_counter() - t_all:.0f} с", flush=True)
    print(f"[book] готово: {out_path} ({len(keys)} ключей)", flush=True)


class OpeningBook:
    """Рантайм-доступ к книге: оценка позиции и выбор хода за микросекунды."""

    def __init__(self, path=BOOK_FILE):
        self.keys = None
        self.scores = None
        self.moves = None
        self.limit = -1
        path = Path(path)
        try:
            with np.load(path) as data:
                self.keys = data["keys"]
                self.scores = data["scores"]
                self.moves = data["moves"]
        except (OSError, FileNotFoundError, ValueError):
            return
        order = np.argsort(self.keys.astype(np.int64))
        self.keys = self.keys[order]
        self.scores = self.scores[order]
        self.moves = self.moves[order]
        self.limit = int(self.moves.max()) if len(self.moves) else -1

    @property
    def available(self):
        return self.keys is not None and len(self.keys)

    def get(self, position, mask, moves=0):
        """Точная оценка канонической позиции или None (нет в книге)."""
        if not self.available or moves < 0 or moves > self.limit:
            return None
        ck = np.uint64(canonical_key(position, mask))
        idx = np.searchsorted(self.keys, ck)
        if idx < len(self.keys) and self.keys[idx] == ck:
            return int(self.scores[idx])
        return None

    def get_by_key(self, ck):
        if not self.available:
            return None
        idx = np.searchsorted(self.keys, np.uint64(ck))
        if idx < len(self.keys) and self.keys[idx] == np.uint64(ck):
            return int(self.scores[idx])
        return None

    def known_children(self, position, mask, moves=0):
        """Оценки детей, присутствующих в книге: [(col, value с точки зрения ходящего)].

        Используется как «частичная» политика: когда не все дети в книге, но
        часть есть — выбирать максимум среди ТОЧНЫХ известных значений (лучше
        грубой эвристики экстренного хода).
        """
        if not self.available or moves < 0:
            return []
        possible = int(((int(mask) + int(BOTTOM_MASK)) & int(BOARD_MASK)) & ~int(mask))
        out = []
        while possible:
            b = possible & -possible
            possible ^= b
            col = (b.bit_length() - 1) // 7
            cpos, cmask = play_bit(np.uint64(position), np.uint64(mask), np.uint64(b))
            child = self.get(cpos, cmask, moves + 1)
            if child is not None:
                out.append((col, -child))
        return out

    def best_move(self, position, mask, moves=0):
        """Лучший ход по оценкам детей из книги; None — отдать солверу.

        Ходующий оценивает -score(ребёнка); ход корректен, только когда
        все играбельные дети присутствуют в книге.
        """
        if not self.available or moves < 0:
            return None
        possible = int(((int(mask) + int(BOTTOM_MASK)) & int(BOARD_MASK)) & ~int(mask))
        best_col, best_val, all_known = None, None, True
        while possible:
            b = possible & -possible
            possible ^= b
            col = (b.bit_length() - 1) // 7
            cpos, cmask = play_bit(np.uint64(position), np.uint64(mask), np.uint64(b))
            child = self.get(cpos, cmask, moves + 1)
            if child is None:
                all_known = False
                break
            value = -child
            if best_val is None or value > best_val:
                best_val, best_col = value, col
        return best_col if all_known else None


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    generate_book(limit)
