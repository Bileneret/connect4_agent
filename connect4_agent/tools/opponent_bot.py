"""Автоматический «друг» для приватной комнаты: заходит по ссылке и ходит
случайными легальными колонками настоящими CDP-кликами (симулирует живого
соперника). В приватной комнате ХОСТ ВСЕГДА СЛЕВА — у гостя «свой ход» = активен
ПРАВЫЙ хронометр (.chronometer:nth). Жмёт Play/Continue при модалах.

Запуск: python tools/opponent_bot.py <port> <room_url> [--moves N]
"""

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, list_tabs  # noqa: E402

READY_JS = r"""
() => {
  const cells = Array.from(document.querySelectorAll('.grid-item'));
  const chronos = Array.from(document.querySelectorAll('.chronometer'));
  const myTurn = chronos.length >= 2
      ? chronos[1].classList.contains('bg-secondary')   // гость справа
      : false;
  const heights = [];
  for (let c = 0; c < 7; c++) {
    let h = 0;
    for (const cell of cells) {
      const m = String(cell.className).match(/cell-(\d+)-(\d+)/);
      if (!m || (+m[2] - 1) !== c) continue;
      const hasPiece = Array.from(cell.querySelectorAll('circle'))
          .some(k => !k.classList.contains('empty-slot'));
      if (hasPiece) h += 1;
    }
    heights.push(h);
  }
  return {cells: cells.length, myTurn, heights, url: location.href};
}
"""

CLICK_COL_JS = r"""
(col) => {
  const cells = Array.from(document.querySelectorAll('.grid-item'));
  const rc = el => el.getBoundingClientRect();
  const inCol = cells.filter(c => {
    const m = String(c.className).match(/cell-\d+-(\d+)/);
    return m && (+m[1] - 1) === col;
  });
  if (!inCol.length) return null;
  const bottom = inCol.reduce((a, b) => rc(a).y > rc(b).y ? a : b);
  const r = rc(bottom);
  return {x: r.x + r.width / 2, y: r.y + r.height / 2};
}
"""


def click_button(page, names) -> bool:
    for name in names:
        try:
            page.get_by_role("button", name=name).first.click(timeout=2500)
            print(f"[friend] нажал «{name}»", flush=True)
            return True
        except Exception:
            continue
    return False


def handle_invite_flow(page, secret: str) -> bool:
    """Экран приглашения: Secret code -> Play -> (Who are you?) -> Continue."""
    st = page.evaluate("() => document.body.innerText.slice(0, 300)")
    if "wants to play with you" in st:
        try:
            page.locator("input:visible").first.fill(secret)
            time.sleep(0.4)
            page.get_by_role("button", name="Play").first.click(timeout=3000)
            print("[friend] ввёл код и нажал Play", flush=True)
            time.sleep(2.0)
        except Exception as exc:  # noqa: BLE001
            print("[friend] код/Play:", type(exc).__name__, flush=True)
            return False
    if "Who are you" in page.evaluate("() => document.body.innerText.slice(0, 300)"):
        try:
            page.locator("input:visible").last.fill("PlayerFriend")
            time.sleep(0.4)
            page.get_by_role("button", name="Continue").first.click(timeout=3000)
            print("[friend] ник отправлен", flush=True)
            time.sleep(2.0)
        except Exception as exc:  # noqa: BLE001
            print("[friend] ник:", type(exc).__name__, flush=True)
    return True


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9223
    secret = sys.argv[2] if len(sys.argv) > 2 else "121"
    tabs = list_tabs(port)
    target = next((t for t in tabs if "papergames" in t.url), None)
    if not target:
        print("[friend] нет вкладки papergames на порту", port)
        return 1
    conn = connect_tab(target)
    try:
        page = conn.page
        print(f"[friend] подключён к {page.url}", flush=True)
        deadline = time.time() + 20 * 60
        moves = 0
        while time.time() < deadline:
            st = page.evaluate(READY_JS)
            if not st["cells"]:
                # экран приглашения / модалы — НИКОГДА не жмём Leave room
                handle_invite_flow(page, secret)
                click_button(page, ["Continue", "Resign"])
                time.sleep(1.5)
                continue
            if st["myTurn"]:
                playable = [c for c, h in enumerate(st["heights"]) if h < 6]
                if playable:
                    col = random.choice(playable)
                    tgt = page.evaluate(CLICK_COL_JS, col)
                    if tgt:
                        page.mouse.click(tgt["x"], tgt["y"])
                        moves += 1
                        print(f"[friend] ход {moves}: колонка {col + 1} "
                              f"(высоты {st['heights']})", flush=True)
                time.sleep(1.2)
                continue
            time.sleep(0.8)
        print(f"[friend] стоп: сделано ходов {moves}", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
