"""Многопроцессный ускоренный прогон тестового набора (для L1_R3 и тяжёлых).

Позиции набора независимы — раскладываются по воркерам multiprocessing (spawn):
каждый воркер со своим движком и ТТ (~0.9 ГБ), результат позиции стримится
в jsonl (resume: уже готовые позиции пропускаются). В конце — сверка точности
с эталонным файлом и суммарная скорость. Однопроцессный бенчмарк остаётся
каноничным гейтом; этот раннер — ускоритель хвоста.

Запуск: python tests/test_benchmark_mp.py --set L1_R3 [--workers 3] [--max-gb 0.9]
"""

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS_DIR = ROOT / "tests" / "data" / "results"
_ENGINE = None


def _worker_init(max_gb):
    global _ENGINE
    from engine.solver_numba import SolverEngine
    _ENGINE = SolverEngine(max_gb=max_gb)


def _worker_solve(args):
    idx, seq, expected, moves = args
    from engine.bitboard import load_position
    t0 = time.perf_counter()
    n0 = _ENGINE.nodes
    position, mask, mv = load_position(seq)
    got = _ENGINE.solve(position, mask, mv if moves is None else moves)
    return {
        "idx": idx,
        "seq": seq,
        "expected": expected,
        "got": got,
        "ok": got == expected,
        "nodes": _ENGINE.nodes - n0,
        "sec": time.perf_counter() - t0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="L1_R3")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-gb", type=float, default=0.9)
    parser.add_argument("--report", type=int, default=10)
    args = parser.parse_args()

    set_name = args.set.replace("Test_", "")
    data_file = ROOT / "tests" / "data" / f"Test_{set_name}"
    results_file = RESULTS_DIR / f"{set_name}.jsonl"
    results_file.parent.mkdir(parents=True, exist_ok=True)

    positions = []
    for line in data_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            seq, score = line.rsplit(None, 1)
            positions.append((seq.strip(), int(score)))
    print(f"[mp] набор {set_name}: {len(positions)} позиций, воркеров {args.workers}", flush=True)

    done = set()
    if results_file.exists():
        with open(results_file, encoding="utf-8") as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)["idx"])
                except (json.JSONDecodeError, KeyError):
                    pass
    tasks = [(i, s, e, None) for i, (s, e) in enumerate(positions) if i not in done]
    print(f"[mp] уже готово {len(done)}, к работе {len(tasks)}", flush=True)
    if not tasks:
        print("[mp] все позиции уже посчитаны; только сводка", flush=True)

    log = open(results_file, "a", encoding="utf-8")
    ok = bad = 0
    nodes_total = 0
    sec_total = 0.0
    t0 = time.perf_counter()
    try:
        with mp.get_context("spawn").Pool(
            processes=args.workers, initializer=_worker_init, initargs=(args.max_gb,)
        ) as pool:
            for res in pool.imap_unordered(_worker_solve, tasks, chunksize=1):
                with open(results_file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(res) + "\n")
                ok += bool(res["ok"])
                bad += not res["ok"]
                nodes_total += res["nodes"]
                sec_total += res["sec"]
                if not res["ok"]:
                    print(f"[mp] РАСХОЖДЕНИЕ: {res['seq']} ожидалось {res['expected']}, "
                          f"получено {res['got']}", flush=True)
                if (ok + bad) % args.report == 0:
                    mps = nodes_total / max(1e-9, sec_total) / 1e6
                    wall = time.perf_counter() - t0
                    left = (len(tasks) - ok - bad) * sec_total / max(1, ok + bad) / args.workers
                    print(f"[mp] {ok + bad}/{len(tasks)} ok={ok} bad={bad} "
                          f"{mps:5.1f} млн узл/с, осталось ~{left / 60:.0f} мин (wall)", flush=True)
    finally:
        log.close()

    total_ok = ok + sum(1 for i in done)  # done раньше считались ok
    print(f"[mp] готово: сеанс ok={ok}, bad={bad}; всего в файле {len(done) + ok + bad}/{len(positions)}",
          flush=True)
    mps = nodes_total / max(1e-9, sec_total) / 1e6
    print(f"[mp] скорость сеанса: {mps:.1f} млн узлов/с "
          f"(параллельная отдача: {nodes_total / max(1e-9, time.perf_counter() - t0) / 1e6:.1f})", flush=True)
    exit_code = 1 if bad else 0
    print(f"[mp] точность сеанса: {100.0 * ok / max(1, ok + bad):.2f}%", flush=True)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
