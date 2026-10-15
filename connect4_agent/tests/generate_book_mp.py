"""Многопроцессная генерация дебютной книги (6+ ply) — ночная фоновая задача.

Раскладка: enumerate_states() конечно-быстро перечисляет все канонические
позиции до глубины limit, задачи сортируются (по ключу — похожие доски рядом,
общая ТТ внутри воркера теплее), пула воркеров решает их независимо, каждая
запись стримится в jsonl (resume при любом обрыве). Периодически (каждые
--checkpoint N новых записей) книга пересобирается в opening_book.npz.
Перед стартом — ожидание свободной ОЗУ (|min-free-gb|), чтобы не наступать
на то же Feast, что вчера: 4 физических ядра не терпят перетоков.

Запуск: python tests/generate_book_mp.py --depth 6 --workers 4 [--max-gb 0.9]
"""

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BOOK_PATH = ROOT / "books" / "opening_book.npz"
RESULTS_PATH = ROOT / "books" / "book6_results.jsonl"
_ENGINE = None


def _worker_init(max_gb):
    from engine.solver_numba import SolverEngine

    global _ENGINE
    _ENGINE = SolverEngine(max_gb=max_gb)


def _worker_solve(task):
    ck, pos, mask, moves = task
    import time as _time

    import numpy as np

    t0 = _time.perf_counter()
    n0 = _ENGINE.nodes
    score = _ENGINE.solve(np.uint64(pos), np.uint64(mask), moves)
    return {
        "ck": ck,
        "moves": moves,
        "score": score,
        "nodes": _ENGINE.nodes - n0,
        "sec": _time.perf_counter() - t0,
    }


def build_npz(results_path, book_path, limit):
    """Собрать npz-книгу из jsonl-результатов (дедуп по ck, сортировка, savez)."""
    import numpy as np

    seen = {}
    if results_path.exists():
        with open(results_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    seen.setdefault(r["ck"], (r["score"], r["moves"]))
                except (json.JSONDecodeError, KeyError):
                    pass
    keys = np.array(sorted(seen), dtype=np.uint64)
    scores = np.zeros(len(keys), dtype=np.int8)
    moves = np.zeros(len(keys), dtype=np.uint8)
    for i, k in enumerate(keys):
        s, m = seen[int(k)]
        scores[i] = s
        moves[i] = m
    book_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = book_path.parent / (book_path.stem + ".tmp.npz")
    np.savez_compressed(tmp, keys=keys, scores=scores, moves=moves)
    os.replace(tmp, book_path)
    return len(keys)


def wait_for_ram(min_free_gb):
    import psutil

    while True:
        free = psutil.virtual_memory().available / 1024 ** 3
        if free >= min_free_gb:
            return free
        print(f"[book-mp] ждём ОЗУ: свободно {free:.1f} ГБ, нужно {min_free_gb}", flush=True)
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-gb", type=float, default=0.9)
    parser.add_argument("--min-free-gb", type=float, default=4.0)
    parser.add_argument("--checkpoint", type=int, default=1000)
    args = parser.parse_args()

    free = wait_for_ram(args.min_free_gb)
    print(f"[book-mp] ОЗУ свободно {free:.1f} ГБ — стартуем", flush=True)

    from engine.opening_book import enumerate_states

    print(f"[book-mp] перечисление состояний до depth {args.depth}...", flush=True)
    t0 = time.perf_counter()
    layers = enumerate_states(args.depth)
    total_states = sum(len(l) for l in layers)
    print(f"[book-mp] состояний: {total_states} "
          + " ".join(f"d{d}:{len(layers[d])}" for d in range(args.depth + 1))
          + f" ({time.perf_counter() - t0:.1f} с)", flush=True)

    tasks = []
    for m in range(args.depth, -1, -1):
        for ck, (pos, mask) in sorted(layers[m].items()):
            tasks.append((ck, pos, mask, m))

    done = set()
    if RESULTS_PATH.exists():
        with open(RESULTS_PATH, encoding="utf-8") as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)["ck"])
                except (json.JSONDecodeError, KeyError):
                    pass
    tasks = [t for t in tasks if t[0] not in done]
    print(f"[book-mp] уже решено {len(done)}, к работе {len(tasks)}, воркеров {args.workers}",
          flush=True)

    resolved = 0
    t0 = time.perf_counter()
    try:
        with mp.get_context("spawn").Pool(
            processes=args.workers, initializer=_worker_init, initargs=(args.max_gb,)
        ) as pool:
            with open(RESULTS_PATH, "a", encoding="utf-8") as fh:
                for res in pool.imap_unordered(_worker_solve, tasks, chunksize=1):
                    fh.write(json.dumps(res) + "\n")
                    fh.flush()
                    resolved += 1
                    if resolved % args.checkpoint == 0:
                        n = build_npz(RESULTS_PATH, BOOK_PATH, args.depth)
                        rate = resolved / max(1e-9, time.perf_counter() - t0)
                        print(f"[book-mp] {resolved}/{len(tasks)} решено ({rate:.2f} поз/с), "
                              f"книга: {n} ключей", flush=True)
    finally:
        n = build_npz(RESULTS_PATH, BOOK_PATH, args.depth)
        print(f"[book-mp] готово: сеанс решено {resolved}, книга {n} ключей -> {BOOK_PATH}",
              flush=True)
        print(f"[book-mp] время сеанса: {(time.perf_counter() - t0) / 3600:.1f} ч", flush=True)


if __name__ == "__main__":
    main()
