"""Разведка шапки ЖИВОГО онлайн-матча (P0.1): подтверждение класса активности.

Режимы:
  * свежий вход: клик «Play online with a random player» → очередь матчмейкинга;
  * продолжение: если очередь уже активна («Finding a random player»), ждём в ней.
При появлении доски — дамп сырой шапки каждые ~0.15 с в течение ~8 с (классы
всех .chronometer и родителей, все элементы с bg-secondary, ник-элементы,
точки-индикаторы, тексты таймеров), затем чтение боевым ридером
(read_papergames) и немедленная сдача. При невыходе соперника — Cancel очереди.

Земная истина «чей сейчас ход» — по ТЕКСТУ убывающего таймера.

Артефакты: logs/recon/online_header_<stamp>.jsonl / .json (+ png).
Запуск: python tools/online_header_probe.py [минут_ожидания]
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402
from browser.dom_reader import read_papergames  # noqa: E402
from config import PLAYER_NAME  # noqa: E402

OUT_DIR = ROOT / "logs" / "recon"
SAMPLE_S = 8.0
SAMPLE_DT = 0.15
QUEUE_MARK = "Finding a random player"

DUMP_JS = r"""
() => {
  const out = {t: Date.now(), url: location.href, vw: window.innerWidth,
               cells: document.querySelectorAll('.grid-item').length,
               chrono: [], bgsec: [], names: [], dots: []};
  const rr = el => { const b = el.getBoundingClientRect();
    return {x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height)}; };
  for (const el of document.querySelectorAll('.chronometer')) {
    out.chrono.push({cls: String(el.className), text: (el.textContent || '').trim(),
                     rect: rr(el),
                     parentCls: el.parentElement ? String(el.parentElement.className) : null});
  }
  for (const el of document.querySelectorAll('[class*="bg-secondary"]')) {
    out.bgsec.push({tag: el.tagName, cls: String(el.className).slice(0, 140),
                    text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40),
                    rect: rr(el)});
  }
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    const b = el.getBoundingClientRect();
    if (b.top > 160 || !b.width || !b.height) continue;
    if (el.children.length) continue;
    const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length > 24 || seen.has(t)) continue;
    seen.add(t);
    out.names.push({text: t, cls: String(el.className).slice(0, 80), rect: rr(el)});
    if (out.names.length >= 40) break;
  }
  for (const el of document.querySelectorAll('body *')) {
    const b = el.getBoundingClientRect();
    if (b.top > 160 || b.width < 8 || b.width > 46 || Math.abs(b.width - b.height) > 8) continue;
    const m = (getComputedStyle(el).backgroundColor || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!m) continue;
    const rgb = [+m[1], +m[2], +m[3]];
    if (Math.max(...rgb) - Math.min(...rgb) < 40) continue;
    out.dots.push({rgb: rgb, rect: rr(el), cls: String(el.className).slice(0, 60)});
  }
  return out;
}
"""

STATE_JS = r"""
() => ({
  url: location.href,
  cells: document.querySelectorAll('.grid-item').length,
  queue: document.body.innerText.includes('Finding a random player'),
  body: document.body.innerText.replace(/\s+/g, ' ').slice(0, 160),
})
"""


def state(page) -> dict:
    try:
        return page.evaluate(STATE_JS)
    except Exception as exc:  # noqa: BLE001
        return {"url": "?", "cells": 0, "queue": False, "body": repr(exc)[:80]}


def get_page():
    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    if target is None:
        return None
    return connect_tab(target)


def click_text(page, pattern: str, timeout_ms: int = 4000) -> bool:
    try:
        page.get_by_role("button", name=pattern).first.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


def analyse(samples: list) -> dict:
    ticking = {0: 0, 1: 0}
    bg_idx = {0: 0, 1: 0}
    for prev, cur in zip(samples, samples[1:]):
        pc, cc = prev.get("chrono") or [], cur.get("chrono") or []
        for i in (0, 1):
            if i < len(pc) and i < len(cc) and pc[i].get("text") != cc[i].get("text"):
                ticking[i] += 1
    for cur in samples:
        cc = cur.get("chrono") or []
        for i in (0, 1):
            if i < len(cc) and "bg-secondary" in (cc[i].get("cls") or ""):
                bg_idx[i] += 1
    active_truth = 0 if ticking[0] >= ticking[1] else 1
    if ticking[0] == ticking[1] == 0:
        active_truth = None
    bgsec_shapes = sorted({f"{s.get('tag')}|{s.get('cls')}" for cur in samples
                           for s in (cur.get("bgsec") or [])})
    bg_only_chrono = all(("chronometer" in (s.get("cls") or ""))
                         for cur in samples for s in (cur.get("bgsec") or []))
    nick = None
    for cur in samples:
        for n in cur.get("names") or []:
            if n.get("text") == PLAYER_NAME:
                nick = "left" if n["rect"]["x"] < cur.get("vw", 1920) / 2 else "right"
                break
        if nick:
            break
    dots = {}
    for cur in samples:
        for d in cur.get("dots") or []:
            side = "left" if d["rect"]["x"] < cur.get("vw", 1920) / 2 else "right"
            dots.setdefault(side, {})
            key = tuple(d["rgb"])
            dots[side][key] = dots[side].get(key, 0) + 1
    return {"ticking": ticking, "bg_idx": bg_idx, "active_truth": active_truth,
            "bg_only_chrono": bg_only_chrono, "bgsec_shapes": bgsec_shapes,
            "nick_side": nick,
            "dots": {k: {str(c): n for c, n in v.items()} for k, v in dots.items()}}


def main():
    wait_s = float(sys.argv[1]) * 60 if len(sys.argv) > 1 else 6 * 60
    conn = get_page()
    if conn is None:
        print("[probe] нет вкладки papergames")
        return 1
    page = conn.page
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl = OUT_DIR / f"online_header_{stamp}.jsonl"
    report = {"stamp": stamp, "player": PLAYER_NAME, "steps": []}
    try:
        st = state(page)
        report["steps"].append({"старт": st})
        if st["cells"]:
            # партия уже идёт: это либо хвост нашей очереди, либо чужая игра —
            # в любом случае сначала смотрим шапку, затем сдаём (роль очереди)
            print(f"[probe] доска уже открыта (url {st['url'][:60]}) — снимаю шапку")
            board_at = 0.0
        else:
            if not st["queue"]:
                if not click_text(page, "Play online"):
                    print("[probe] кнопка «Play online» не найдена:", st["body"][:200])
                    return 1
                print("[probe] матчмейкинг — клик Play online", flush=True)
            else:
                print("[probe] уже в очереди матчмейкинга — продолжаю ждать", flush=True)

            t0 = time.time()
            board_at = None
            next_note = 30.0
            while time.time() - t0 < wait_s:
                cur = state(page)
                if cur["cells"]:
                    board_at = round(time.time() - t0, 2)
                    break
                if not cur["queue"] and time.time() - t0 > 5:
                    # очередь пропала (модал/сброс) — пробуем один раз снова
                    report["steps"].append({"очередь исчезла": cur["body"]})
                    click_text(page, "Continue")
                    click_text(page, "Play online")
                    time.sleep(1.0)
                if time.time() - t0 > next_note:
                    print(f"[probe] в очереди {int(time.time() - t0)} с…", flush=True)
                    next_note += 30.0
                time.sleep(0.4)
            if board_at is None:
                report["result"] = f"соперник не найден за {wait_s / 60:.0f} мин"
                click_text(page, "Cancel")
                time.sleep(1.0)
                report["steps"].append({"после Cancel": state(page)})
                print("[probe]", report["result"], "— очередь отменена")
                return 1

        report["board_at_s"] = board_at
        print(f"[probe] партия началась — снимаю {SAMPLE_S:.0f} с…", flush=True)
        try:
            page.screenshot(path=str(OUT_DIR / f"online_header_{stamp}.png"))
        except Exception:
            pass

        samples = []
        t1 = time.time()
        with jsonl.open("w", encoding="utf-8") as fh:
            while time.time() - t1 < SAMPLE_S:
                try:
                    s = page.evaluate(DUMP_JS)
                except Exception as exc:  # noqa: BLE001
                    s = {"error": repr(exc)}
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
                samples.append(s)
                time.sleep(SAMPLE_DT)
        try:
            snap = read_papergames(page)
            report["reader"] = {"my_turn": snap.my_turn, "active_side": snap.active_side,
                                "moves": snap.moves, "timers": snap.timers,
                                "errors": snap.raw_errors}
        except Exception as exc:  # noqa: BLE001
            report["reader"] = {"error": repr(exc)}

        print(f"[probe] снято {len(samples)} сэмплов; сдаюсь…", flush=True)
        for _ in range(2):
            click_text(page, "Resign", 3000)
            time.sleep(0.9)
            if not state(page)["cells"]:
                break
        report["resigned"] = not state(page)["cells"]
        if not report["resigned"]:
            click_text(page, "Abort", 2500)
            time.sleep(1.0)
            report["resigned"] = not state(page)["cells"]

        report["analysis"] = analyse(samples)
        a = report["analysis"]
        print("=" * 60)
        print("АНАЛИЗ ШАПКИ ОНЛАЙН-МАТЧА")
        print("  тикал таймер:      ", a["ticking"], " (индексы DOM)")
        print("  bg-secondary на:   ", a["bg_idx"], "-> земная истина:", a["active_truth"])
        print("  bg-secondary только у .chronometer:", a["bg_only_chrono"])
        if a["bgsec_shapes"]:
            print("  формы элементов с bg-secondary:", a["bgsec_shapes"][:6])
        print("  наш ник:", a["nick_side"])
        print("  точки-индикаторы:", json.dumps(a["dots"], ensure_ascii=False))
        print("  ридер:", json.dumps(report.get("reader"), ensure_ascii=False))
        print("  сдача:", report["resigned"], "| артефакты:", jsonl.name)
        print("=" * 60)
        return 0
    finally:
        try:
            (OUT_DIR / f"online_header_{stamp}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("online_header_probe", force="--force" in sys.argv)
    sys.exit(main())
