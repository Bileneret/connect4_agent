"""Серия рематчей против робота по кнопке «Play again!» (указание пользователя
15.10: для этой серии правило Q12 «не жать Play again» отменено; сам игровой
цикл бота кнопку не трогает — её жмёт только этот инструмент).

v2 (по итогам разбора серии 16:20):
  * конец раунда подтверждается КНОПКОЙ «Play again!», а не нулём клеток
    (ложные «концы» при перерисовке больше не дают мусорных «?»);
  * в каждой партии в лог пишется: кто начинал, первый ход робота, счёт
    камней (наш/их), признак ничьей по тексту финального экрана;
  * результат считается по дельте счёта (как и раньше).

Играет живой бот (run.py --live).
Запуск: python tools/rematch_series.py [партий=100] [отчёт_каждые=3]
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402

POLL_S = 1.5
PLAYER_NAME = "Player"

STATE_JS = r"""
() => {
  const cells = document.querySelectorAll('.grid-item').length;
  const scores = [];
  for (const e of document.querySelectorAll('.score')) {
    const r = e.getBoundingClientRect();
    if (r.top > 140 || !r.width) continue;
    const t = (e.textContent || '').trim();
    if (/^\d+$/.test(t)) scores.push(t);
  }
  let ours = 0, theirs = 0, total = 0, firstCol = null, firstOwner = null;
  for (const c of document.querySelectorAll('.grid-item')) {
    const k = Array.from(c.querySelectorAll('circle')).find(x => !x.classList.contains('empty-slot'));
    if (!k) continue;
    const cls = String(k.getAttribute('class') || '');
    const isOurs = cls.includes('circle-light');   // робо-партии: мы слева (light)
    total += 1;
    if (isOurs) ours += 1; else theirs += 1;
    const m = String(c.className).match(/cell-(\d+)-(\d+)/);
    if (m && (+m[1]) === 6 && firstCol === null) {
      firstCol = +m[2] - 1; firstOwner = isOurs ? 1 : 2;
    }
  }
  const btns = Array.from(document.querySelectorAll('button, [role="button"]'))
      .map(b => (b.textContent || '').replace(/\s+/g, ' ').trim());
  return {cells: cells, scores: scores.slice(0, 2), ours: ours, theirs: theirs,
          total: total, firstCol: firstCol, firstOwner: firstOwner,
          play_again: btns.some(t => /^Play again/i.test(t)),
          body: document.body.innerText.replace(/\s+/g, ' ').slice(0, 200)};
}
"""


def state(page):
    try:
        return page.evaluate(STATE_JS)
    except Exception as exc:  # noqa: BLE001
        return {"cells": 0, "scores": [], "ours": 0, "theirs": 0, "total": 0,
                "firstCol": None, "firstOwner": None,
                "play_again": False, "body": repr(exc)[:60]}


def get_page():
    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    if target is None:
        return None
    return connect_tab(target)


def click_play_again(page) -> bool:
    for kw in ({"timeout": 5000, "force": True}, {"timeout": 5000}):
        try:
            page.get_by_role("button", name="Play again").first.click(**kw)
            return True
        except Exception:
            continue
    return False


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    every = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    conn = get_page()
    if conn is None:
        print("[rematch] нет вкладки papergames")
        return 1
    page = conn.page
    results = []
    wins = losses = draws = unknown = 0
    print(f"[rematch] СТАРТ v2: план {n} партий, замер каждые {every}", flush=True)
    try:
        st = state(page)
        if not st["cells"]:
            if st["play_again"]:
                click_play_again(page)
                print("[rematch] старт: нажал Play again (висел финал)", flush=True)
            else:
                try:
                    page.goto("https://papergames.io/en/connect4", timeout=20000)
                    time.sleep(2.0)
                    page.get_by_role("button", name="Play vs robot").first.click(timeout=6000)
                    print("[rematch] старт: начал матч с роботом", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print("[rematch] не смог начать матч:", type(exc).__name__, flush=True)
        for i in range(1, n + 1):
            # ждём начало раунда
            t0 = time.time()
            started = False
            while time.time() - t0 < 90:
                st = state(page)
                if st["cells"]:
                    started = True
                    break
                if st["play_again"]:
                    click_play_again(page)
                time.sleep(POLL_S)
            if not started:
                print(f"[{i}/{n}] доска не появилась за 90 с — пропуск", flush=True)
                results.append("?")
                unknown += 1
                continue
            before = st["scores"]
            # кто начинал + первый ход робота (по первому наблюдению доски)
            starter = None
            opener = None
            if st["total"] == 1:
                starter = "мы" if st["firstOwner"] == 1 else "Carlito"
                opener = (st["firstCol"] or 0) + 1
                first_seen_total = 1
            else:
                first_seen_total = st["total"]
            # ждём ПОДТВЕРЖДЁННЫЙ конец раунда: нет клеток И видна «Play again!»
            t1 = time.time()
            finished = False
            end_state = None
            while time.time() - t1 < 420:
                s = state(page)
                if not s["cells"] and s["play_again"]:
                    finished = True
                    end_state = s
                    break
                if not s["cells"]:
                    time.sleep(0.5)     # перерисовка: подождём кнопку
                else:
                    time.sleep(POLL_S)
            if not finished:
                print(f"[{i}/{n}] раунд не завершился за 7 мин — пропуск", flush=True)
                results.append("?")
                unknown += 1
                continue
            after = end_state["scores"]
            draw_hint = ("draw" in end_state["body"].lower())
            res = "?"
            try:
                a, b = int(before[0]), int(before[1])
                a2, b2 = int(after[0]), int(after[1])
                if a2 > a:
                    res = "W"; wins += 1
                elif b2 > b:
                    res = "L"; losses += 1
                else:
                    res = "D" if draw_hint else "="
                    if res == "D":
                        draws += 1
                    else:
                        unknown += 1
            except Exception:  # noqa: BLE001
                unknown += 1
            results.append(res)
            print(f"[{i}/{n}] {res} | старт={starter or f'?({first_seen_total} камней)'}"
                  f" первыйход_робота={opener} | наш={end_state['ours']} их={end_state['theirs']}"
                  f" | счёт {after} | {'НИЧЬЯ-экран ' if draw_hint else ''}{end_state['body'][:60]}",
                  flush=True)
            if i % every == 0:
                tail = " ".join(results[-every:])
                print(f"=== ЗАМЕР {i // every}: партии {i - every + 1}-{i}: {tail} | "
                      f"ИТОГО: W{wins} L{losses} D{draws} ?{unknown} из {i} ===", flush=True)
            if i < n:
                if not click_play_again(page):
                    print(f"[{i}] Play again не нажался — попробую в следующем цикле", flush=True)
                time.sleep(1.0)
    finally:
        print(f"[rematch] ИТОГ СЕРИИ: побед {wins}, поражений {losses}, ничьих {draws}, "
              f"непонятных {unknown}, всего {len(results)} из {n}", flush=True)
        print("[rematch] по партиям: " + " ".join(results), flush=True)
        conn.close()
    return 0


if __name__ == "__main__":
    # P1.3: инструмент задуман для совместной работы с запущенным ботом (run.py --live)
    from state.bot_lock import ensure_bot
    ensure_bot("rematch_series", force="--force" in sys.argv)
    sys.exit(main())
