"""Раннер приёмочной серии: N матчей бот-vs-робот с замером результата.

Цикл каждого матча: тост по протоколу (скилл windows-push-notification)
-> пауза 5 с -> вход в СВЕЖУЮ партию (хвосты предыдущих сдаются resign'ом)
-> ожидание финала (доска исчезла) -> чтение History -> парсинг результата.

Требует запущенного бота (run.py --live) — он подхватывает игру автоматически.
Никаких других вмешательств в браузер во время серии быть не должно.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402

TOAST = str(Path.home() / ".zcode/skills/windows-push-notification/scripts/send-toast.sh")
HISTORY_RE = re.compile(r"\(\d+\)(\d)(\d)\s*Connect\s*4", re.S)
# Живой формат строки (проверено 16.10): "Player (1500)Sofia (2669)10 Connect 4 <дата>"
# где "10" = наш счёт 1, счёт соперника 0 (победа); "01" = поражение.
DATE_RE = re.compile(r"(Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep)\s+\d+,\s+\d{4},\s+[\d:]+\s+[AP]M")
# финальный экран матча: "16 Player 02:47 0 1000 Carlito 03:41 1"
SCORE_RE = re.compile(r"([A-Za-z0-9_@.\-]+)\s+(\d{1,2}:\d{2})\s+(\d+)")


def parse_end_screen(body: str):
    """Результат прямо с финального экрана (без навигации в History)."""
    if not body:
        return None, "финальный экран пуст"
    ours = theirs = None
    for m in SCORE_RE.finditer(body):
        name, score = m.group(1), int(m.group(3))
        if name == "Player" and ours is None:
            ours = score
        elif name != "Player" and theirs is None and not name.isdigit():
            theirs = score
    if ours is not None and theirs is not None:
        return ours > theirs, f"{ours}:{theirs} (финальный экран)"
    return None, f"финальный экран не распознан: {body[:120]}"


def toast(text: str):
    try:
        subprocess.run(["bash", TOAST, text], capture_output=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"[series] тост не отправлен: {exc}", flush=True)


def get_page():
    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    if not target:
        return None
    return connect_tab(target)


def board_cells(page) -> int:
    try:
        return page.evaluate("() => document.querySelectorAll('.grid-item').length")
    except Exception:
        return 0


def resign_leftover(page) -> bool:
    """Если висит недоконченная партия — сдать её (чистый слот под серию)."""
    if not board_cells(page):
        return False
    print("[series] обнаружен хвост партии — сдаю (resign)", flush=True)
    try:
        page.get_by_role("button", name="Resign").first.click(timeout=3000)
        time.sleep(0.6)
        page.get_by_role("button", name="Resign").first.click(timeout=3000)
        time.sleep(1.5)
    except Exception as exc:  # noqa: BLE001
        print("[series] resign хвоста не удался:", type(exc).__name__, flush=True)
    return True


def start_fresh_game(page) -> bool:
    for attempt in (1, 2):
        try:
            page.get_by_role("button", name="Play vs robot").first.click(timeout=5000)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[series] кнопка Play vs robot недоступна (попытка {attempt}): "
                  f"{type(exc).__name__}", flush=True)
            if attempt == 1:
                # жёсткий возврат на страницу игры (могли остаться в History/др.)
                try:
                    page.goto("https://papergames.io/en/connect4", timeout=20000)
                    time.sleep(2.5)
                except Exception as nav_exc:  # noqa: BLE001
                    print("[series] goto не удался:", type(nav_exc).__name__, flush=True)
    else:
        return False
    time.sleep(1.0)
    try:
        page.wait_for_selector("mat-select", timeout=2500)
        page.locator("mat-select").first.click()
        time.sleep(0.5)
        page.locator("mat-option", has_text="Connect").first.click(timeout=2500)
        time.sleep(0.3)
        page.get_by_role("button", name="Continue").first.click(timeout=3000)
    except Exception:  # noqa: BLE001 — модал мог не появиться (запомненный выбор)
        pass
    deadline = time.time() + 12
    while time.time() < deadline:
        if board_cells(page):
            return True
        time.sleep(0.4)
    return False


def wait_match_end(page, max_s: float = 420.0):
    """Ждём появления доски и затем её исчезновения (матч завершён).

    Возврат: (finished, финальный_текст_страницы).
    """
    seen = False
    t0 = time.time()
    while time.time() - t0 < max_s:
        n = board_cells(page)
        if n:
            seen = True
        elif seen:
            time.sleep(2.0)  # дать странице до-перейти
            body = ""
            try:
                body = page.evaluate(
                    "() => document.body.innerText.replace(/\\s+/g, ' ').slice(0, 600)")
            except Exception:  # noqa: BLE001
                pass
            return True, body
        time.sleep(2.0)
    return False, ""


def read_last_result(page):
    """Открыть History и вернуть (наша_победа: bool|None, детали) последнего матча."""
    for attempt in (1, 2):
        try:
            page.goto("https://papergames.io/en/connect4", timeout=20000)
            time.sleep(1.5)
            page.get_by_text("History", exact=True).first.click(force=True, timeout=5000)
            time.sleep(2.0)
            rows = page.evaluate("""() => {
              const seen = [];
              for (const el of document.querySelectorAll('div, li, tr')) {
                const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (t.includes('Player') && t.includes('Connect 4')
                        && t.includes('(') && t.length < 300) seen.push(t);
              }
              return [...new Set(seen)].slice(0, 5);
            }""")
            if not rows:
                return None, "нет строк истории"
            for row in rows:                       # первая строка, которая парсится
                m = HISTORY_RE.search(row)
                if m:
                    ours, theirs = int(m.group(1)), int(m.group(2))
                    return ours > theirs, f"{ours}:{theirs} | {row[:120]}"
            return None, rows[0][:160]
        except Exception as exc:  # noqa: BLE001
            last = f"ошибка чтения истории (попытка {attempt}): {type(exc).__name__}"
            time.sleep(1.0)
    return None, last


def back_to_game_page(page):
    try:
        page.get_by_text("Connect 4", exact=True).first.click(timeout=4000)
        time.sleep(1.5)
    except Exception:  # noqa: BLE001
        pass


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    wins = losses = unknown = 0
    results = []
    conn = None
    try:
        conn = get_page()
        if conn is None:
            print("[series] нет вкладки papergames")
            return 1
        page = conn.page
        for i in range(1, n + 1):
            print(f"[series] --- матч {i}/{n} ---", flush=True)
            resign_leftover(page)
            toast(f"Приёмка: матч {i}/{n} — бот играет мышью. Не двигайте курсор.")
            time.sleep(5)  # протокол: пауза 5 с после уведомления
            if not start_fresh_game(page):
                print("[series] не удалось начать партию, пауза 10 с и повтор", flush=True)
                time.sleep(10)
                if not start_fresh_game(page):
                    results.append(("не начался", i))
                    unknown += 1
                    continue
            print(f"[series] партия {i} началась, ждём финал...", flush=True)
            ended, final_body = wait_match_end(page)
            if not ended:
                print("[series] таймаут ожидания финала — пропуск итерации", flush=True)
                results.append(("таймаут ожидания", i))
                unknown += 1
                continue
            time.sleep(2.0)
            won, detail = parse_end_screen(final_body)
            if won is None:                    # фолбэк: History (если финал не распознан)
                won, detail = read_last_result(page)
                back_to_game_page(page)
            if won is True:
                wins += 1
                mark = "ПОБЕДА"
            elif won is False:
                losses += 1
                mark = "поражение"
            else:
                unknown += 1
                mark = f"неизвестно ({detail})"
            print(f"[series] матч {i}: {mark} | {detail}", flush=True)
            results.append((mark, i))
            back_to_game_page(page)
            time.sleep(1.0)
    finally:
        if conn:
            conn.close()
    total = wins + losses
    wr = (100.0 * wins / total) if total else 0.0
    print("=" * 60, flush=True)
    print(f"[series] ИТОГ: побед {wins}, поражений {losses}, неясных {unknown}, "
          f"винрейт {wr:.1f}% (из {total} учтённых)", flush=True)
    for mark, i in results:
        print(f"    матч {i}: {mark}", flush=True)
    return 0


if __name__ == "__main__":
    # P1.3: задуман для совместной работы с запущенным ботом (run.py --live)
    from state.bot_lock import ensure_bot
    ensure_bot("acceptance_series", force="--force" in sys.argv)
    sys.exit(main())
