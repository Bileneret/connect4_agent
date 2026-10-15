"""Быстро войти в партию против робота (без ходов) и оставить бота играть.

Навигация идёт через CDP-клики (не физическая мышь); ходы делает уже
живой игровой цикл (run.py --live). Спринт ≤15 с из-за 40-секундного лимита.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402


def main():
    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    if not target:
        print("нет вкладки papergames")
        return 1
    conn = connect_tab(target)
    try:
        page = conn.page
        # возврат на страницу игры (могли остаться в History/Shop и т.п.)
        if "connect4" not in page.url:
            page.goto("https://papergames.io/en/connect4", timeout=20000)
            time.sleep(2.5)
        if page.evaluate("() => document.querySelectorAll('.grid-item').length"):
            print("доска уже на экране — игра идёт")
            return 0
        page.get_by_role("button", name="Play vs robot").first.click(timeout=5000)
        time.sleep(0.8)
        try:
            page.wait_for_selector("mat-select", timeout=3000)
            page.locator("mat-select").first.click()
            time.sleep(0.6)
            page.locator("mat-option", has_text="Connect").first.click(timeout=3000)
            time.sleep(0.4)
            page.get_by_role("button", name="Continue").first.click(timeout=4000)
        except Exception as exc:  # noqa: BLE001
            print("  (модал выбора игры пропущен:", type(exc).__name__, ")")
        deadline = time.time() + 12
        while time.time() < deadline:
            n = page.evaluate("() => document.querySelectorAll('.grid-item').length")
            if n:
                who = page.evaluate(
                    "() => { const c = document.querySelector('.chronometer');"
                    " return c ? (c.classList.contains('bg-secondary') ? 'наш ход' : 'ход соперника')"
                    " : '?'; }")
                print(f"доска на экране ({n} клеток), {who} — передаю боту")
                return 0
            time.sleep(0.4)
        print("доска не появилась")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
