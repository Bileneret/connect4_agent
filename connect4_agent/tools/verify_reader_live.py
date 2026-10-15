"""Живая проверка read_papergames: вход в игру -> чтение -> ход -> чтение -> resign.

Спринт укладывается в ~15 секунд (у каждого игрока 4 минуты на партию).
Проверяет: пустая доска читается как пустая; после нашего хода в колонку
появляется зелёная фишка в нужной клетке; передача хода (bg-secondary у
таймера соперника); класс клетки фишки (для сверки col/row-семантики).
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402
from browser.dom_reader import read_papergames  # noqa: E402


def click_text(page, pattern):
    r = page.evaluate(
        "(pat) => { const el = Array.from(document.querySelectorAll('button, a'))"
        ".find(e => new RegExp(pat, 'i').test(e.textContent || ''));"
        " if (!el) return null; const b = el.getBoundingClientRect();"
        " return {x: b.x + b.width/2, y: b.y + b.height/2}; }", pattern)
    if r:
        page.mouse.click(r["x"], r["y"])
    return r


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
        # 1) старт игры с роботом — нативными локаторами Playwright
        page.get_by_role("button", name="Play vs robot").first.click(timeout=5000)
        time.sleep(0.8)
        try:
            page.wait_for_selector("mat-select", timeout=3000)
            page.locator("mat-select").first.click()
            time.sleep(0.6)
            page.wait_for_selector("mat-option", timeout=3000)
            page.locator("mat-option", has_text="Connect").first.click()
            time.sleep(0.4)
            page.get_by_role("button", name="Continue").first.click(timeout=4000)
        except Exception as exc:
            print("  (шаг выбора игры пропущен:", type(exc).__name__, ")")
        time.sleep(1.2)
        # 2) ждём доску
        deadline = time.time() + 10
        n = 0
        while time.time() < deadline:
            n = page.evaluate("() => document.querySelectorAll('.grid-item').length")
            if n:
                break
            time.sleep(0.3)
        if not n:
            print("FAIL: доска не появилась (клеток", n, ")")
            return 1
        # 3) чтение пустой доски нашим ридером
        snap = read_papergames(page)
        print("ЧТЕНИЕ 1: клеток-в-сетке:", len(snap.grid), "x", len(snap.grid[0]),
              "| фишек:", snap.moves, "| наш ход:", snap.my_turn,
              "| таймеры:", snap.timers)
        print("  высоты:", snap.heights, "| ошибки:", snap.raw_errors)
        assert snap.moves == 0, "доска не пуста?"
        # 4) наш ход в центральную колонку (индекс 3) — настоящей мышью
        cx, cy = snap.col_centers_client[3]
        page.mouse.click(cx, cy)
        time.sleep(0.9)
        snap2 = read_papergames(page)
        print("ЧТЕНИЕ 2: фишек:", snap2.moves, "| наш ход:", snap2.my_turn,
              "| высоты:", snap2.heights, "| таймеры:", snap2.timers)
        piece_cls = page.evaluate(
            "() => { const c = Array.from(document.querySelectorAll('.grid-item'))"
            ".find(x => Array.from(x.querySelectorAll('circle'))"
            ".some(k => !k.classList.contains('empty-slot')));"
            " return c ? String(c.className) : null; }")
        print("  класс клетки с фишкой:", piece_cls)
        assert snap2.moves == 1 and snap2.heights[3] == 1, "наш ход не отражён в сетке"
        assert snap2.grid[0][3] == 1, "фишка в клетке не распознана как наша (зелёная)"
        assert not snap2.my_turn, "ход не передался сопернику (bg-secondary не ушёл)"
        # 5) вежливый выход
        if click_text(page, "^(resign|abort)"):
            time.sleep(0.6)
            click_text(page, "^resign$")
        print("ЖИВАЯ ПРОВЕРКА read_papergames: OK")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("verify_reader_live", force="--force" in sys.argv)
    sys.exit(main())
