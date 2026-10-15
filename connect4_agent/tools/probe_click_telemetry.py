"""Одна телеметрированная физическая попытка клика: где ломается цепочка.

Шаги: робастный подъём окна браузера (обход foreground-lock через трюк с Alt),
проверка GetForegroundWindow/WindowFromPoint, pyautogui.size()/position,
один плавный клик по нижней ячейке колонки, mss-снимок цели до и после.
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from actuator.mouse_controller import (  # noqa: E402
    MouseController, find_browser_window, top_level_at,
)
from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402
from browser.dom_reader import read_papergames  # noqa: E402

user32 = ctypes.windll.user32


def window_title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def force_foreground(hwnd) -> bool:
    """Робастный подъём окна: трюк с нажатием Alt снимает foreground-lock."""
    user32.keybd_event(0x12, 0, 0, 0)          # Alt down
    ok = user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)          # Alt up
    return bool(ok)


def mss_point(x, y, half=8):
    from mss import mss
    with mss() as sct:
        p = np.asarray(sct.grab({"left": x - half, "top": y - half,
                                 "width": 2 * half, "height": 2 * half}))[:, :, :3]
    return p.reshape(-1, 3).mean(axis=0)[::-1].round(0)


def main():
    import pyautogui

    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    conn = connect_tab(target)
    try:
        page = conn.page
        n = page.evaluate("() => document.querySelectorAll('.grid-item').length")
        print("клеток в DOM:", n)
        if not n:
            print("не в игре — сначала tools/enter_robot_game.py")
            return 1
        snap = read_papergames(page)
        print("наш ход:", snap.my_turn, "| фишек:", snap.moves)

        hwnd = find_browser_window()
        print("окно браузера:", hwnd, repr(window_title(hwnd)))
        print("foreground ДО:", repr(window_title(user32.GetForegroundWindow())))
        print("pyautogui.size():", pyautogui.size(), "| позиция:", pyautogui.position())
        print("SetForegroundWindow ->", force_foreground(hwnd))
        time.sleep(0.3)
        print("foreground ПОСЛЕ:", repr(window_title(user32.GetForegroundWindow())))

        col = 3
        cx, cy = snap.col_center_screen_px(col)
        sx, sy = int(cx), int(cy)
        print(f"цель клика (наши экранные пикс): ({sx},{sy}), dpr={snap.dpr}")
        print("WindowFromPoint в цели:", top_level_at(sx, sy) == hwnd,
              "| top_level:", top_level_at(sx, sy), "| браузер:", hwnd)
        print("пиксель цели ДО :", mss_point(sx, sy))

        mc = MouseController()
        plan = mc.plan_column_click((cx, cy), (snap.board_rect['w'] / 7 / 2) * snap.dpr)
        print("план: цель", tuple(round(v) for v in plan.target),
              "| точек", len(plan.points), "| hover", plan.hover_ms, "мс")
        mc.click(plan, apply=True)
        time.sleep(0.5)
        print("позиция курсора ПОСЛЕ:", pyautogui.position())
        time.sleep(1.2)
        print("пиксель цели ПОСЛЕ:", mss_point(sx, sy))
        snap2 = read_papergames(page)
        print("после клика: фишек", snap2.moves, "| наш ход", snap2.my_turn)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("probe_click_telemetry", force="--force" in sys.argv)
    sys.exit(main())
