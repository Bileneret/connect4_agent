"""Физическое управление системным курсором — Вопросы №3, №8, №39, №41, №47.

Курсор плавно уводится к цели по квадратичной кривой Безье со случайной
контрольной точкой (естественная дуга), в целевую точку добавляется гауссов
микро-сдвиг внутри радиуса клетки 0.5·r. Клик — аппаратный: mouseDown ->
пауза 40-75 мс -> mouseUp (pyautogui поверх SendInput). pyautogui.FAILSAFE
включён: увод курсора в угол экрана мгновенно ставит бота на паузу (Q47).

apply=False — сухой прогон: строится и возвращается полный план (точки пути,
цель, тайминги), курсор НЕ двигается. Это позволяет тестировать и репетировать
без Computer Use; реальные движения — только с apply=True при живом запуске.
"""

from __future__ import annotations

import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import HOVER_MAX_MS, HOVER_MIN_MS  # noqa: E402


@dataclass
class ClickPlan:
    start: tuple[float, float]
    target: tuple[float, float]
    points: list[tuple[float, float]]
    hover_ms: int
    down_ms: int
    jitter: tuple[float, float] = field(default=(0.0, 0.0))


class MouseController:
    """Планировщик и исполнитель физических кликов (DPI-aware координаты)."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self._last_pos: tuple[float, float] | None = None
    def plan_column_click(self, cell_center: tuple[float, float],
                          cell_radius: float,
                          start: tuple[float, float] | None = None) -> ClickPlan:
        """План клика: центр нижней ячейки + гауссов сдвиг, плавный путь.

        cell_center/cell_radius — в физических пикселях экрана (после учёта DPI).
        """
        if start is None:
            start = self._last_pos or (cell_center[0], cell_center[1] - 220)
        # гауссов микро-сдвиг, ограниченный кругом 0.5 радиуса (Q41)
        sigma = cell_radius * 0.22
        limit = cell_radius * 0.5
        dx = dy = limit * 2
        while dx * dx + dy * dy > limit * limit:
            dx = self.rng.gauss(0, sigma)
            dy = self.rng.gauss(0, sigma)
        target = (cell_center[0] + dx, cell_center[1] + dy)

        # контрольная точка Безье: середина + случайный перпендикулярный снос
        mx, my = (start[0] + target[0]) / 2, (start[1] + target[1]) / 2
        vx, vy = target[0] - start[0], target[1] - start[1]
        norm = math.hypot(vx, vy) or 1.0
        px, py = -vy / norm, vx / norm
        bow = self.rng.uniform(0.04, 0.16) * norm
        ctrl = (mx + px * bow + self.rng.gauss(0, 3), my + py * bow + self.rng.gauss(0, 3))

        steps = max(8, int(norm / 22))
        points = []
        for i in range(steps + 1):
            t = i / steps
            bx = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * ctrl[0] + t * t * target[0]
            by = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * ctrl[1] + t * t * target[1]
            points.append((bx, by))
        hover_ms = self.rng.randint(HOVER_MIN_MS, HOVER_MAX_MS)
        down_ms = self.rng.randint(40, 75)
        return ClickPlan(start=start, target=target, points=points,
                         hover_ms=hover_ms, down_ms=down_ms, jitter=(dx, dy))

    # --- исполнение ---------------------------------------------------------
    def click(self, plan: ClickPlan, apply: bool = True) -> ClickPlan:
        """Выполнить план (или сухой прогон при apply=False)."""
        if not apply:
            self._last_pos = plan.target
            return plan
        import pyautogui  # только в момент реального исполнения

        pyautogui.FAILSAFE = True  # увод в угол => исключение => пауза (Q47)
        per_seg = (plan.hover_ms / 1000.0) / max(1, len(plan.points) - 1)
        for x, y in plan.points:
            pyautogui.moveTo(int(round(x)), int(round(y)))
            time.sleep(per_seg * self.rng.uniform(0.6, 1.4))
        pyautogui.mouseDown()
        time.sleep(plan.down_ms / 1000.0)
        pyautogui.mouseUp()
        self._last_pos = plan.target
        return plan


# --- окно браузера и гарантия точки клика (Q38) -----------------------------
def find_browser_window(title_parts=("Connect 4", "Microsoft Edge", "Google Chrome",
                                     "Brave", "Opera", "Yandex")):
    """HWND видимого окна браузера по частям заголовка (EnumWindows)."""
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum_cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        title = buf.value or ""
        if any(part.lower() in title.lower() for part in title_parts):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_cb, 0)
    return found[0] if found else None


def find_browser_window_for_port(port: int):
    """HWND главного окна браузера, запущенного с этим отладочным портом.

    Детерминированно: по командной строке процесса ищем `--remote-debugging-port=<port>`,
    затем среди видимых окон с этим PID берём окно класса Chrome_WidgetWin_1.
    Нужно потому, что при нескольких окнах браузера заголовки похожи.
    """
    import ctypes
    import ctypes.wintypes as wt
    import subprocess

    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe' "
        "or Name='brave.exe'\" | "
        f"Where-Object {{$_.CommandLine -like '*remote-debugging-port={port}*'}} | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=25)
        pid = int(out.stdout.strip().splitlines()[0])
    except Exception:
        return None

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def enum_cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        wpid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value.startswith("Chrome_WidgetWin") and user32.GetWindow(hwnd, 4) == 0:
            found.append(hwnd)   # 4 = GW_OWNER: главное окно без владельца
            return False
        return True

    user32.EnumWindows(enum_cb, 0)
    return found[0] if found else None


def ensure_foreground(hwnd) -> bool:
    """Поднять окно наверх (развернуть, если свёрнуто).

    Windows блокирует смену фокуса фоновым процессам — классический обход:
    краткое синтетическое нажатие Alt снимает foreground-lock, и следующий
    SetForegroundWindow проходит. Проверка реального результата — по
    GetForegroundWindow (не только по коду возврата).
    """
    import ctypes
    import time

    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    for _ in range(3):
        if user32.GetForegroundWindow() == hwnd:
            return True
        user32.keybd_event(0x12, 0, 0, 0)          # Alt down
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)          # Alt up
        time.sleep(0.15)
    return user32.GetForegroundWindow() == hwnd


def top_level_at(x: int, y: int):
    """HWND верхнеуровневого окна, которому принадлежит точка экрана."""
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    hwnd = user32.WindowFromPoint(wt.POINT(int(x), int(y)))
    if not hwnd:
        return None
    return user32.GetAncestor(hwnd, 2)  # GA_ROOT

