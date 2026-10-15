"""Диагностика геометрии клика и фокуса окна — БЕЗ физических кликов.

Проверяет гипотезы провала первого живого прогона:
  1) наша формула CSS->экранных пикселей указывает на доску? (цвет пикселя через mss)
  2) какое окно Windows лежит в целевой точке (WindowFromPoint) и в фокусе ли браузер.
Выводит все сырые величины для калибровки формулы.
"""

import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import connect_tab, find_debug_ports, list_tabs  # noqa: E402
from browser.dom_reader import read_papergames  # noqa: E402

user32 = ctypes.windll.user32


def window_title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def main():
    tabs = []
    for p in find_debug_ports():
        tabs.extend(list_tabs(p))
    target = next((t for t in tabs if "papergames" in t.url), None)
    if not target:
        print("нет вкладки papergames")
        return 1
    conn = connect_tab(target)
    try:
        page = conn.page
        n = page.evaluate("() => document.querySelectorAll('.grid-item').length")
        if not n:
            print("не в игре — запустите tools/enter_robot_game.py и повторите пробу")
            return 1

        snap = read_papergames(page)
        js = page.evaluate("""() => ({
            screenX: window.screenX, screenY: window.screenY,
            outerW: window.outerWidth, outerH: window.outerHeight,
            innerW: window.innerWidth, innerH: window.innerHeight,
            dpr: window.devicePixelRatio,
            left: window.screenLeft, top: window.screenTop,
            availLeft: window.screen.availLeft, availTop: window.screen.availTop,
            availW: window.screen.availWidth, availH: window.screen.availHeight,
            screenW: window.screen.width, screenH: window.screen.height,
        })""")
        print("JS-геометрия:", json.dumps(js, ensure_ascii=False))
        print("снимок: dpr", snap.dpr, "chrome_top", snap.chrome_top_px,
              "screen", snap.screen_x, snap.screen_y)
        print("доска (CSS):", snap.board_rect)

        for col in (0, 3, 6):
            cx, cy = snap.col_centers_client[col]
            css_x = snap.screen_x + cx
            css_y = snap.screen_y + snap.chrome_top_px + cy
            sx, sy = int(css_x * snap.dpr), int(css_y * snap.dpr)
            print(f"колонка {col}: client=({cx:.0f},{cy:.0f}) "
                  f"-> экранная оценка (dpr-формула) = ({sx},{sy})")

        cx, cy = snap.col_centers_client[3]
        sx, sy = int((snap.screen_x + cx) * snap.dpr), int((snap.screen_y + snap.chrome_top_px + cy) * snap.dpr)

        # пиксель по нашей формуле
        from mss import mss
        with mss() as sct:
            shot = np.asarray(sct.grab({"left": sx - 15, "top": sy - 15, "width": 30, "height": 30}))[:, :, :3]
        print(f"пиксель у точной формулы ({sx},{sy}): средний RGB =",
              shot.reshape(-1, 3).mean(axis=0)[::-1].round(0))

        # пиксель по формуле БЕЗ dpr (если процесс уже DPI-aware, JS CSS == физические)
        sx2, sy2 = int(snap.screen_x + cx), int(snap.screen_y + snap.chrome_top_px + cy)
        with mss() as sct:
            shot2 = np.asarray(sct.grab({"left": sx2 - 15, "top": sy2 - 15, "width": 30, "height": 30}))[:, :, :3]
        print(f"пиксель без dpr ({sx2},{sy2}): средний RGB =",
              shot2.reshape(-1, 3).mean(axis=0)[::-1].round(0))

        # окна Windows в этих точках и в фокусе
        fg = user32.GetForegroundWindow()
        print(f"ФОКУС: '{window_title(fg)}'")
        for label, (px, py) in {"с-dpr": (sx, sy), "без-dpr": (sx2, sy2)}.items():
            hwnd = user32.WindowFromPoint(wt.POINT(px, py))
            proc_pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_pid))
            print(f"WindowFromPoint[{label}] ({px},{py}): hwnd={hwnd} pid={proc_pid.value} "
                  f"'{window_title(hwnd)}'")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    # P1.3: при живом боте не вмешиваемся в страницу без явного --force
    from state.bot_lock import ensure_no_bot
    ensure_no_bot("probe_geometry", force="--force" in sys.argv)
    sys.exit(main())
