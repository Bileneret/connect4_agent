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


def live(auto=True):
    """Живой автопилот: CDP-подключение, книга, движок, физическая мышь (Этапы 5-7)."""
    from config import TARGET_URL_HINT
    from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs
    from engine.opening_book import OpeningBook
    from engine.ponder import PonderManager
    from engine.solver_numba import SolverEngine
    from actuator.hotkeys import HotkeyDispatcher
    from actuator.mouse_controller import MouseController
    from state.game_loop import GameLoop, run_forever
    from state.session_manager import SessionManager

    if auto:
        ports = find_debug_ports()
        if not ports:
            print("Нет живого порта отладки CDP. Сначала запустите браузер с "
                  "--remote-debugging-port=9222 (см. browser/cdp_connector.py).")
            return 1
        tabs = []
        for p in ports:
            tabs.extend(list_tabs(p))
        target = next((t for t in tabs if TARGET_URL_HINT in t.url), None)
        if target is None:
            print("Вкладка papergames.io не найдена. Откройте игру и повторите.")
            return 1
        conn = connect_tab(target)
        browser_port = target.port
    else:
        # Q1: интерактивный выбор браузера/вкладки (нумерованный список)
        from browser.cdp_connector import choose_and_connect
        conn = choose_and_connect(interactive=True)
        if conn is None:
            return 1
        browser_port = conn.info.port
    print(f"Подключено к: {conn.info.title} | {conn.info.url} (порт {browser_port})")

    engine = SolverEngine()
    book = OpeningBook()
    print(f"Книга: {'загружена, ' + format(len(book.keys), ',') + ' ключей' if book.available else 'нет'}")

    ponder = PonderManager(engine, workers=2)  # Q28: фоновая работа в живом цикле
    session = SessionManager(state_path=ROOT / "logs" / "session_state.json")
    if session.restore():
        print(f"[run] восстановлено состояние прошлой сессии: раунд {session.st.round_no}, "
              f"ходов {session.st.moves} (Q45)")
    mouse = MouseController()
    loop = GameLoop(page=conn.page, engine=engine, book=book, session=session,
                    mouse=mouse, apply_clicks=True, mode="auto", ponder=ponder,
                    browser_port=browser_port)

    dispatcher = HotkeyDispatcher()
    dispatcher.bind("toggle_mode", lambda: setattr(
        loop, "mode", "hint" if loop.mode == "auto" else "auto"))
    dispatcher.bind("pause", lambda: setattr(loop, "paused", not loop.paused))
    dispatcher.bind("resync", lambda: print("[run] F9: ресинк (логика в цикле)"))
    dispatcher.bind("exit", lambda: setattr(loop, "running", False))
    try:
        dispatcher.register()
    except Exception as exc:  # noqa: BLE001 — без админ-прав хуки могут не встать
        print(f"[run] глобальные хоткеи недоступны: {exc}")
    try:
        run_forever(loop)
    finally:
        try:
            dispatcher.unregister()
        except Exception:
            pass
    return 0


def main():
    parser = argparse.ArgumentParser(description="Connect4 бот для PaperGames.io")
    parser.add_argument("--selftest", action="store_true",
                        help="проверка окружения и ядра (по умолчанию)")
    parser.add_argument("--live", action="store_true",
                        help="живой автопилот в уже открытой вкладке papergames.io")
    parser.add_argument("--interactive", action="store_true",
                        help="с --live: интерактивный выбор браузера/вкладки (Q1)")
    args = parser.parse_args()

    enable_dpi_awareness()

    if args.live:
        return live(auto=not args.interactive)
    # Этап 1: без --live — проверка окружения и ядра.
    return selftest()


if __name__ == "__main__":
    sys.exit(main())
