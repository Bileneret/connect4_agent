"""Зондирование живого интерфейса papergames.io: скриншот + скан DOM.

Подключается к браузеру (порт отладки), снимает скриншот страницы в файл
и печатает кандидатов на селекторы доски/шапки/таймеров для dom_reader.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402

OUT_PNG = ROOT / "tests" / "fixtures" / "papergames_probe.png"

SCAN_JS = r"""
() => {
  const rect = (el) => { const r = el.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; };
  const info = {title: document.title, url: location.href, ready: document.readyState};

  info.canvases = Array.from(document.querySelectorAll('canvas')).map(c => ({
    id: c.id, cls: String(c.className || '').slice(0, 60),
    size: c.width + 'x' + c.height, rect: rect(c)
  }));

  const rx = /(board|grid|cell|disk|token|slot|drop|column|circle|piece|chip|row)/i;
  const cand = new Map();
  for (const el of document.querySelectorAll('*')) {
    const cls = String(el.className && el.className.toString ? el.className.toString() : '');
    if (rx.test(cls)) {
      const key = el.tagName + '.' + cls.trim().split(/\s+/).slice(0, 3).join('.');
      const entry = cand.get(key) || {n: 0, rect: null};
      entry.n++;
      if (!entry.rect) entry.rect = rect(el);
      cand.set(key, entry);
    }
  }
  info.candidates = Array.from(cand.entries())
      .sort((a, b) => b[1].n - a[1].n).slice(0, 30)
      .map(([k, v]) => [k, v.n, v.rect]);

  info.svgCount = document.querySelectorAll('svg').length;
  info.svgCircles = document.querySelectorAll('circle').length;
  info.svgSamples = Array.from(document.querySelectorAll('svg')).slice(0, 6).map(s => ({
    cls: String(s.getAttribute('class') || '').slice(0, 50),
    kids: s.children.length, rect: rect(s)
  }));

  info.btns = Array.from(document.querySelectorAll('button, a'))
      .filter(b => /play|game|robot|играть|бот|room|нов/i.test(b.textContent || ''))
      .slice(0, 12)
      .map(b => ({tag: b.tagName, text: (b.textContent || '').trim().slice(0, 40)}));
  return info;
}
"""


def main():
    ports = find_debug_ports()
    print("живые порты:", ports)
    if not ports:
        print("НЕТ живого порта отладки")
        return 1
    tabs = []
    for p in ports:
        tabs.extend(list_tabs(p))
    for t in tabs:
        print(f"  порт {t.port}: [{t.title[:50]}] {t.url[:90]}")
    target = next((t for t in tabs if "papergames" in t.url), None)
    if not target:
        print("вкладка papergames не найдена")
        return 1

    conn = connect_tab(target)
    try:
        page = conn.page
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20000)
        except Exception:
            pass
        time.sleep(4)  # дать странице дорисоваться
        info = page.evaluate(SCAN_JS)
        print(json.dumps(info, ensure_ascii=False, indent=1)[:4500])
        page.screenshot(path=str(OUT_PNG))
        print("скриншот сохранён:", OUT_PNG)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("discover_papergames", force="--force" in sys.argv)
    sys.exit(main())
