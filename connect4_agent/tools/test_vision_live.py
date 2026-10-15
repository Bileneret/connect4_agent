"""Живой тест vision-фолбёка: сравнение экранного чтения с DOM-чтением.

Вход в робо-игру, пара ходов (CDP), затем: DOM-снимок даёт эталонную сетку,
VisionReader читает ту же доску с ЭКРАНА (mss по геометрии из DOM) —
сверяем клетки. Область берётся в CSS/виртуальных координатах (тестовый
процесс НЕ DPI-aware — mss и CSS живут в одном пространстве).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from browser.cdp_connector import connect_tab, list_tabs  # noqa: E402
from browser.dom_reader import read_papergames  # noqa: E402
from browser.vision_fallback import VisionReader, VisionRegion  # noqa: E402


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9222
    tabs = list_tabs(port)
    t = next(x for x in tabs if "papergames" in x.url)
    conn = connect_tab(t)
    try:
        page = conn.page
        if "connect4" not in page.url:
            page.goto("https://papergames.io/en/connect4", timeout=20000)
            time.sleep(2)
        if not page.evaluate("() => document.querySelectorAll('.grid-item').length"):
            page.get_by_role("button", name="Play vs robot").first.click(timeout=5000)
            time.sleep(1.0)
            try:
                page.wait_for_selector("mat-select", timeout=2500)
                page.locator("mat-select").first.click(); time.sleep(0.5)
                page.locator("mat-option", has_text="Connect").first.click(timeout=2500)
                time.sleep(0.3)
                page.get_by_role("button", name="Continue").first.click(timeout=3000)
            except Exception:
                pass
            for _ in range(30):
                if page.evaluate("() => document.querySelectorAll('.grid-item').length"):
                    break
                time.sleep(0.4)
        print("доска на экране ✓")
        # делаем 3 хода (CDP), ставим свои и даём роботу ответить
        for col in (3, 2):
            page.evaluate("""(col) => {
                const cells = Array.from(document.querySelectorAll('.grid-item'));
                const rc = el => el.getBoundingClientRect();
                const inCol = cells.filter(c => {
                    const m = String(c.className).match(/cell-\\d+-(\\d+)/);
                    return m && (+m[1] - 1) === col; });
                const bottom = inCol.reduce((a, b) => rc(a).y > rc(b).y ? a : b);
                bottom.click();
            }""", col)
            time.sleep(2.5)
        snap = read_papergames(page)
        # Q38 для зрения: окно с игрой обязано быть ВИДИМЫМ на экране —
        # поднимаем окно браузера перед захватом экрана (Alt-трюк)
        from actuator.mouse_controller import (
            ensure_foreground, find_browser_window_for_port,
        )
        hwnd = find_browser_window_for_port(port)
        print("окно браузера:", hwnd, "| поднято:", ensure_foreground(hwnd) if hwnd else "—")
        time.sleep(0.5)
        print("DOM-сетка (низ вверх):")
        for row in snap.grid:
            print("   ", row)
        # ЗРЕНИЕ БЕЗ DOM-ГЕОМЕТРИИ: широкий кадр -> сами ищем доску на экране
        big = VisionRegion(left=300, top=120, width=1250, height=780)
        vr = VisionReader(big)
        img = vr.capture(big)
        grid_v, heights_v, box = vr.locate_and_read(img)
        if grid_v is None:
            print("НЕ УДАЛОСЬ НАЙТИ ДОСКУ НА КАДРЕ")
            return 2
        print("найденная пластина доски:", box)
        print("VISION-сетка:")
        for row in grid_v:
            print("   ", row)
        # сверка
        ok = bad = 0
        for r in range(6):
            for c in range(7):
                if grid_v[r][c] == snap.grid[r][c]:
                    ok += 1
                else:
                    bad += 1
        print(f"СВЕРКА: совпало {ok}/42, расхождений {bad}")
        if bad:
            for r in range(6):
                for c in range(7):
                    if grid_v[r][c] != snap.grid[r][c]:
                        print(f"   клетка ({r},{c}): dom={snap.grid[r][c]} vision={grid_v[r][c]}")
        # сохраним сырой кадр для глаза
        import numpy as np, zlib, struct
        img = vr.capture()
        raw = b"".join(b"\x00" + img[y].tobytes() for y in range(img.shape[0]))
        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", img.shape[1], img.shape[0], 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
        out = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "vision_frame.png"
        out.write_bytes(png)
        print("кадр зрения:", out)
        # вежливый выход
        try:
            page.get_by_role("button", name="Resign").first.click(timeout=2500); time.sleep(0.5)
            page.get_by_role("button", name="Resign").first.click(timeout=2000)
        except Exception:
            pass
        return 0 if bad == 0 else 2
    finally:
        conn.close()


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("test_vision_live", force="--force" in sys.argv)
    sys.exit(main())
