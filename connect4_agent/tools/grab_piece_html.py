"""Спринт «HTML фишки»: вход в игру -> один ход -> ДАМП разметки фишки -> выход.

Укладывается в 15 секунд (лимит хода 40 с). Печатает точный innerHTML клетки
с фишкой и все её элементы/заливки — источник истины для детектора фишек.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402

DUMP = ROOT / "tests" / "fixtures" / "piece_html_dump.json"


def main():
    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    conn = connect_tab(target)
    try:
        page = conn.page
        # войти в игру, если не в ней
        if not page.evaluate("() => document.querySelectorAll('.grid-item').length"):
            page.get_by_role("button", name="Play vs robot").first.click(timeout=5000)
            time.sleep(1.0)
            try:
                page.wait_for_selector("mat-select", timeout=2500)
                page.locator("mat-select").first.click()
                time.sleep(0.5)
                page.locator("mat-option", has_text="Connect").first.click(timeout=2500)
                time.sleep(0.3)
                page.get_by_role("button", name="Continue").first.click(timeout=3000)
            except Exception:  # noqa: BLE001
                pass
            deadline = time.time() + 10
            while time.time() < deadline:
                if page.evaluate("() => document.querySelectorAll('.grid-item').length"):
                    break
                time.sleep(0.3)
        # базовый HTML пустой клетки
        base = page.evaluate("""() => {
            const c = document.querySelector('.grid-item');
            return c ? {cls: String(c.className), html: c.innerHTML} : null; }""")
        # наш ход? клик в колонку по нижней ячейке (CDP)
        tgt = page.evaluate("""() => {
            const cells = Array.from(document.querySelectorAll('.grid-item'));
            const rc = el => el.getBoundingClientRect();
            if (!cells.length) return null;
            const xs = [...new Set(cells.map(c => Math.round(rc(c).x)))].sort((a,b)=>a-b);
            const inCol = cells.filter(c => Math.round(rc(c).x) === xs[3]);
            const bottom = inCol.reduce((a,b) => rc(a).y > rc(b).y ? a : b);
            const r = rc(bottom);
            bottom.click();
            return {x: r.x + r.width/2, y: r.y + r.height/2}; }""")
        time.sleep(2.0)  # ждём анимацию появления фишки
        dump = page.evaluate("""() => {
            const cells = Array.from(document.querySelectorAll('.grid-item'));
            const out = {filled: [], samples: []};
            for (const c of cells) {
                const html = c.innerHTML;
                // отличить фишку от пустой клетки по НАЛИЧИЮ чего-то кроме span>svg>circle.empty-slot
                const nonSlot = Array.from(c.querySelectorAll('circle, rect, path, div, img, use'))
                    .some(el => !(el.tagName === 'CIRCLE' && el.classList.contains('empty-slot')));
                if (nonSlot) out.filled.push({cls: String(c.className), html: html.slice(0, 700)});
            }
            // детальный состав первых двух фишек + заливки
            for (const f of out.filled.slice(0, 2)) {
                const c = document.querySelector('.' + f.cls.split(' ').join('.'));
                if (!c) continue;
                out.samples.push({
                    cls: f.cls,
                    elements: Array.from(c.querySelectorAll('*')).map(el => ({
                        tag: el.tagName,
                        cls: String(el.getAttribute('class') || ''),
                        fill: getComputedStyle(el).fill,
                        stroke: getComputedStyle(el).stroke,
                        bg: getComputedStyle(el).backgroundColor,
                    })),
                });
            }
            return out;
        }""")
        dump["base"] = base
        dump["click"] = tgt
        DUMP.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
        print("клеток с фишкой:", len(dump["filled"]), "| дамп:", DUMP)
        if dump["filled"]:
            print("HTML фишки:", dump["filled"][0]["html"][:400])
        # вежливый выход из партии
        try:
            page.get_by_role("button", name="Resign").first.click(timeout=2500)
            time.sleep(0.5)
            page.get_by_role("button", name="Resign").first.click(timeout=2000)
        except Exception as exc:  # noqa: BLE001
            print("resign:", type(exc).__name__)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("grab_piece_html", force="--force" in sys.argv)
    sys.exit(main())
