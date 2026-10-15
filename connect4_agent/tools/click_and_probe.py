"""Клик по элементу с текстом и повторный скан страницы (для живого зондирования)."""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402
from discover_papergames import SCAN_JS  # noqa: E402

OUT_PNG = ROOT / "tests" / "fixtures" / "papergames_game.png"

CLICK_TEXT_JS = r"""
(text) => {
  const els = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
  const el = els.find(e => (e.textContent || '').toLowerCase().includes(text));
  if (!el) return {clicked: false, seen: els.map(e => (e.textContent||'').trim().slice(0,30)).slice(0,20)};
  el.click();
  return {clicked: true, tag: el.tagName, text: (el.textContent || '').trim().slice(0, 60)};
}
"""


def connect_page():
    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    if not target:
        raise SystemExit("вкладка papergames не найдена")
    return connect_tab(target)


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "play vs robot"
    conn = connect_page()
    try:
        page = conn.page
        res = page.evaluate(CLICK_TEXT_JS, text.lower())
        print("клик:", json.dumps(res, ensure_ascii=False))
        if not res.get("clicked"):
            return 1
        time.sleep(5)
        info = page.evaluate(SCAN_JS)
        slim = {k: info[k] for k in ("title", "url", "ready", "canvases", "svgCount",
                                     "svgCircles", "svgSamples", "candidates", "btns")}
        print(json.dumps(slim, ensure_ascii=False, indent=1)[:4200])
        page.screenshot(path=str(OUT_PNG))
        print("скриншот:", OUT_PNG)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("click_and_probe", force="--force" in sys.argv)
    sys.exit(main())
