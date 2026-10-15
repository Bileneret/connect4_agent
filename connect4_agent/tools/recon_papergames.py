"""Живая разведка papergames.io одним спринтом (всё за ~10 секунд).

Полный цикл: Play vs robot -> выбор игры в дропдауне -> Continue ->
снимок структуры пустой доски -> ход настоящей мышью -> снимок с фишкой ->
Abort game. Все клики — настоящие (Playwright mouse), иначе Angular Material
не открывает дропдауны. Результат — JSON-дамп + скриншоты.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402

DUMP = ROOT / "tests" / "fixtures" / "papergames_recon2.json"

PROBE_JS = r"""
() => {
  const rect = el => { const r = el.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; };
  const parse = s => { const m = (s||'').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return m ? [+m[1], +m[2], +m[3]] : null; };
  const cells = Array.from(document.querySelectorAll('.grid-item'));
  const board = cells.length ? cells[0].parentElement : null;
  const filled = cells.filter(c => c.querySelectorAll('*').length > 0).map(c => ({
      rect: rect(c), cls: String(c.className).slice(0, 80),
      inner: c.innerHTML.slice(0, 260),
      kid_bg: Array.from(c.children).map(k => parse(getComputedStyle(k).backgroundColor))
  }));
  return {
    url: location.href, n_cells: cells.length,
    board: board ? {tag: board.tagName, cls: String(board.className).slice(0, 140),
                    rect: rect(board)} : null,
    cell0_html: cells.length ? cells[0].outerHTML.slice(0, 300) : null,
    cell_cls: cells.length ? String(cells[0].className) : null,
    filled_count: filled.length, filled: filled.slice(0, 5),
    chronos: Array.from(document.querySelectorAll('.chronometer')).map(el => ({
        cls: String(el.className), text: el.textContent.trim(),
        bg: parse(getComputedStyle(el).backgroundColor), rect: rect(el)})),
  };
}
"""


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
    report = {}
    try:
        page = conn.page
        report["robot_btn"] = click_text(page, "play vs robot")
        time.sleep(1.0)
        # дропдаун выбора игры
        sel = page.evaluate(
            "() => { const s = document.querySelector('mat-select, [role=\"combobox\"]');"
            " if (!s) return null; const b = s.getBoundingClientRect();"
            " return {x: b.x + b.width/2, y: b.y + b.height/2}; }")
        report["select_rect"] = sel
        if sel:
            page.mouse.click(sel["x"], sel["y"])
            time.sleep(0.8)
            opts = page.evaluate(
                "() => Array.from(document.querySelectorAll('mat-option, [role=\"option\"]'))"
                ".map(o => { const b = o.getBoundingClientRect();"
                " return {text: (o.textContent||'').trim().slice(0,40),"
                " x: b.x + b.width/2, y: b.y + b.height/2, w: Math.round(b.width)}; })")
            report["options"] = opts
            pick = next((o for o in opts if "connect" in o["text"].lower()), None)
            report["picked"] = pick
            if pick:
                page.mouse.click(pick["x"], pick["y"])
                time.sleep(0.6)
        report["continue_btn"] = click_text(page, "^continue$|continue")
        time.sleep(1.5)
        # ожидание доски
        deadline = time.time() + 10
        n = 0
        while time.time() < deadline:
            n = page.evaluate("() => document.querySelectorAll('.grid-item').length")
            if n:
                break
            time.sleep(0.4)
        report["cells"] = n
        if not n:
            report["screen"] = page.evaluate(PROBE_JS)
            DUMP.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            page.screenshot(path=str(ROOT / "tests" / "fixtures" / "recon2_fail.png"))
            print("доски нет; дамп:", DUMP)
            return 1
        report["before"] = page.evaluate(PROBE_JS)
        page.screenshot(path=str(ROOT / "tests" / "fixtures" / "recon2_empty.png"))
        # немедленный ход в колонку 1 (индекс 1) настоящей мышью
        tgt = page.evaluate("""
        (col) => {
          const cells = Array.from(document.querySelectorAll('.grid-item'));
          const rc = el => el.getBoundingClientRect();
          const xs = [...new Set(cells.map(c => Math.round(rc(c).x)))].sort((a, b) => a - b);
          if (!xs.length || col >= xs.length) return null;
          const inCol = cells.filter(c => Math.round(rc(c).x) === xs[col]);
          const bottom = inCol.reduce((a, b) => (rc(a).y > rc(b).y ? a : b));
          const r = rc(bottom);
          return {x: r.x + r.width/2, y: r.y + r.height/2};
        }""", 1)
        report["click_target"] = tgt
        if tgt:
            page.mouse.click(tgt["x"], tgt["y"])
            time.sleep(1.0)
            report["after"] = page.evaluate(PROBE_JS)
            page.screenshot(path=str(ROOT / "tests" / "fixtures" / "recon2_after_move.png"))
        report["abort"] = click_text(page, "abort")
        time.sleep(0.8)
        DUMP.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print("дамп:", DUMP)
        b = report.get("before", {})
        print("до входа: клеток", b.get("n_cells"), "| board:", json.dumps(b.get("board"), ensure_ascii=False))
        a = report.get("after", {})
        print("после хода: фишек", a.get("filled_count"), "| хроно:",
              json.dumps(a.get("chronos"), ensure_ascii=False)[:300])
        print("filled[0]:", json.dumps((a.get("filled") or [{}])[0], ensure_ascii=False)[:400])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
