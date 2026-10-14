"""Гейт Этапа 4: официальный бенчмарк математического ядра.

Тестовые наборы Паскаля Понса (blog.gamesolver.org/solving-connect-four,
страница "Test protocol"): каждая строка — "<ходы> <точная оценка>".
Приёмочные критерии (утверждены в вопросе №50):
    * 100% совпадение точных оценок на всех проверенных наборах;
    * средняя скорость >= 5 млн узлов/с (после прогрева JIT).

Запуск:  python tests/test_benchmark.py [--data DIR] [--sets L3_R1,...]
         [--max-gb 4.0] [--progress N]
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import GATE_MIN_NODES_PER_SEC  # noqa: E402
from engine.solver_numba import SolverEngine  # noqa: E402

SMOKE_CASES = [
    ("", 1),          # пустая доска: победа 1-го игрока на 41-м камне (известный факт)
    ("4", -1),        # после центра выигрывает 1-й => ходящий 2-й получает -1
    ("1122334", 18),  # немедленная победа ходящего: (43 - 6) // 2
    ("112233", 18),   # соперник завершает четвёрку прямо сейчас
]


def iter_positions(path: Path):
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        seq, score = line.rsplit(None, 1)
        yield seq, int(score)


def set_sort_key(name: str):
    """От быстрых к медленным: END (R1) -> MIDDLE (R2) -> BEGIN (R3); внутри L3->L1."""
    order = {}
    for i, part in enumerate(name.replace("Test_", "").split("_")):
        order[part[0]] = -int(part[1]) if part[0] == "L" else int(part[1])
    return (order.get("R", 0), order.get("L", 0))


def run_smoke(engine):
    failures = []
    for seq, expected in SMOKE_CASES:
        try:
            got = engine.solve_sequence(seq)
        except ValueError as exc:
            failures.append((seq or "<пусто>", expected, f"ошибка загрузки: {exc}"))
            continue
        if got != expected:
            failures.append((seq or "<пусто>", expected, got))
    return failures


def run_set(engine, path: Path, progress_every: int):
    ok = 0
    bad = []
    n0 = engine.nodes
    t0 = time.perf_counter()
    for i, (seq, expected) in enumerate(iter_positions(path), 1):
        try:
            position, mask, moves = engine.load_sequence(seq)
            got = engine.solve(position, mask, moves)
        except ValueError as exc:
            bad.append((seq, expected, f"ошибка загрузки: {exc}"))
            continue
        if got == expected:
            ok += 1
        else:
            bad.append((seq, expected, got))
        if progress_every and i % progress_every == 0:
            rate = (engine.nodes - n0) / max(1e-9, time.perf_counter() - t0) / 1e6
            print(f"    ... {i:4d}  ok={ok}  bad={len(bad)}  {rate:6.1f} млн узлов/с", flush=True)
    dt = time.perf_counter() - t0
    return ok, bad, engine.nodes - n0, dt


def main():
    parser = argparse.ArgumentParser(description="Бенчмарк ядра (Этап 4)")
    parser.add_argument("--data", default=str(ROOT / "tests" / "data"))
    parser.add_argument("--sets", default="all", help="через запятую, например L2_R1,L1_R1")
    parser.add_argument("--max-gb", type=float, default=4.0)
    parser.add_argument("--progress", type=int, default=100)
    parser.add_argument("--show-mismatches", type=int, default=10)
    args = parser.parse_args()

    data_dir = Path(args.data)
    if args.sets == "all":
        files = sorted(data_dir.glob("Test_*"), key=lambda p: set_sort_key(p.name))
    else:
        files = [data_dir / f"Test_{s.strip()}" for s in args.sets.split(",")]
    files = [f for f in files if f.is_file()]
    if not files:
        print(f"Не найдено ни одного набора в {data_dir}")
        return 2

    print("=" * 74)
    print("ГЕЙТ ЭТАПА 4: бенчмарк математического ядра (наборы Паскаля Понса)")
    print("=" * 74)

    engine = SolverEngine(max_gb=args.max_gb)
    gb = engine.tt_bytes / 1024 ** 3
    print(f"Таблица транспозиций: {engine.tt['pairs']:,} корзин x 2 слота = "
          f"{engine.tt_bytes / 1024 ** 3:.2f} ГБ ({engine.tt['entries']:,} записей)")

    print("Прогрев JIT (первая компиляция, кэшируется на диск)...")
    tw = time.perf_counter()
    engine.solve_sequence("4")
    engine.solve_sequence("1122334")
    engine.solve_sequence("112233")
    print(f"Прогрев завершён за {time.perf_counter() - tw:.1f} с")

    smoke_bad = run_smoke(engine)
    if smoke_bad:
        print("СМОУК-ТЕСТ ПРОВАЛЕН:")
        for seq, exp, got in smoke_bad:
            print(f"    {seq!r}: ожидалось {exp}, получено {got}")
        return 1
    print("Смоук-тест: 4/4 верно (пустая=1, '4'=-1, немедленные выигрыши=18)")

    total_ok = 0
    total_bad = 0
    total_nodes = 0
    total_dt = 0.0
    all_bad = []
    print("-" * 74)
    for path in files:
        ok, bad, nodes, dt = run_set(engine, path, args.progress)
        total_ok += ok
        total_bad += len(bad)
        total_nodes += nodes
        total_dt += dt
        mps = nodes / max(1e-9, dt) / 1e6
        status = "OK" if not bad else "FAIL"
        print(f"[{status}] {path.name}: {ok}/{ok + len(bad)} точных, "
              f"{nodes / 1e6:.0f} узлов, {mps:6.1f} млн узлов/с, "
              f"в среднем {1000 * dt / max(1, ok + len(bad)):.1f} мс/позиция", flush=True)
        for seq, exp, got in bad[: args.show_mismatches]:
            print(f"       расхождение: {seq} ожидалось {exp}, получено {got}")
        all_bad.extend((path.name,) + b for b in bad)

    overall_mps = total_nodes / max(1e-9, total_dt) / 1e6
    accuracy = 100.0 * total_ok / max(1, total_ok + total_bad)
    print("-" * 74)
    print(f"Позиций проверено: {total_ok + total_bad} (верно: {total_ok}, ошибок: {total_bad})")
    print(f"Точность: {accuracy:.2f}%   Скорость: {overall_mps:.1f} млн узлов/с")
    if total_bad:
        print(f"Всего расхождений: {len(all_bad)} (первые 20 ниже)")
        for name, seq, exp, got in all_bad[:20]:
            print(f"    [{name}] {seq}: ожидалось {exp}, получено {got}")

    acc_ok = total_bad == 0
    speed_ok = overall_mps * 1e6 >= GATE_MIN_NODES_PER_SEC
    print("=" * 74)
    print(f"КРИТЕРИЙ ТОЧНОСТИ (100%): {'ПРОЙДЕН' if acc_ok else 'НЕ ПРОЙДЕН'}")
    print(f"КРИТЕРИЙ СКОРОСТИ (>= {GATE_MIN_NODES_PER_SEC // 1_000_000} млн узлов/с): "
          f"{'ПРОЙДЕН' if speed_ok else 'НЕ ПРОЙДЕН'}")
    print("ИТОГ ЭТАПА 4: " + ("ЯДРО ПРИНЯТО" if acc_ok and speed_ok else "ЯДРО НЕ ПРИНЯТО"))
    return 0 if (acc_ok and speed_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
