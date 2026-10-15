"""Чтение раздела History на papergames.io — итоги последних матчей.

Открывает историю в UI (клик по пункту меню), снимает список матчей
(соперник/результат/время, если доступны) и делает скриншот. Используется
для автоматического подсчёта винрейта серии приёмки.
"""

import json
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
    conn = connect_tab(target)
    try:
        page = conn.page
        print("стартовый URL:", page.url,
              "| клеток:", page.evaluate("() => document.querySelectorAll('.grid-item').length"))

        # клик по пункту History в левом меню (нативный локатор)
        try:
            page.get_by_text("History", exact=True).first.click(timeout=4000)
        except Exception as exc:  # noqa: BLE001
            print("клик History не удался:", type(exc).__name__)
            return 1
        time.sleep(2.0)
        print("после клика URL:", page.url)

        dump = page.evaluate("""() => {
          const rows = [];
          // ищем повторяющиеся строки-элементы списка
          const cand = Array.from(document.querySelectorAll('div, li, tr'))
            .filter(el => {
              const r = el.getBoundingClientRect();
              return r.height > 30 && r.height < 120 && r.width > 300 && r.top > 40;
            });
          for (const el of cand.slice(0, 80)) {
            const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (t && t.length > 4 && t.length < 160) rows.push(t);
          }
          return {rows: [...new Set(rows)].slice(0, 30)};
        }""")
        print(json.dumps(dump, ensure_ascii=False, indent=1)[:1800])
        page.screenshot(path=str(ROOT / "tests" / "fixtures" / "history.png"))
        print("скриншот: history.png")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
