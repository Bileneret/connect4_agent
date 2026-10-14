"""Единая точка входа бота (Вопрос №49).

Этап 1: проверка окружения, прогрев JIT-кэша ядра.
Этапы 5-6 (браузер, мышь, хоткеи) подключаются в последующих итерациях.
"""

import argparse
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[0]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def enable_dpi_awareness():
    """Per-Monitor DPI Aware (Вопрос №8) — точность экранных координат."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def selftest():
    try:
        import psutil
    except ImportError:
        print("psutil не установлен: pip install -r requirements.txt")
        return 1

    vm = psutil.virtual_memory()
    print(f"ОЗУ: всего {vm.total / 1024**3:.1f} ГБ, доступно {vm.available / 1024**3:.1f} ГБ")

    from engine.solver_numba import SolverEngine
    from config import TT_MAX_GB, TT_RAM_FRACTION
    engine = SolverEngine(max_gb=TT_MAX_GB, ram_fraction=TT_RAM_FRACTION)
    print(f"Таблица транспозиций: {engine.tt_bytes / 1024**3:.2f} ГБ "
          f"({engine.tt['entries']:,} записей)")

    print("Прогрев JIT...")
    engine.solve_sequence("4")
    engine.solve_sequence("1122334")
    engine.solve_sequence("112233")
    print(f"Ядро готово (JIT скомпилирован и кэширован), узлов при прогоне: {engine.nodes:,}")

    checks = [("", 1), ("4", -1), ("1122334", 18), ("112233", 18)]
    for seq, expected in checks:
        got = engine.solve_sequence(seq)
        mark = "OK " if got == expected else "FAIL"
        shown = seq if seq else "пустая доска"
        print(f"  [{mark}] solve({shown}) = {got} (ожидалось {expected})")
        if got != expected:
            return 1
    print("Ядро работает корректно. Браузерная интеграция будет подключена на Этапе 5.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Connect4 бот для PaperGames.io")
    parser.add_argument("--selftest", action="store_true",
                        help="зарезервировано; до Этапа 5 выполняется проверка окружения")
    parser.parse_args()

    enable_dpi_awareness()

    # Этап 1: единственный режим — selftest; игровой цикл появится на Этапе 5.
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
