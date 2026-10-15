"""Клики через CDP (DevTools) — без дёргания физического курсора.

Playwright page.mouse.* шлёт Input.dispatchMouseEvent: браузер доставляет эти
события как ДОВЕРЕННЫЕ (isTrusted=true), для страницы они неотличимы от живой
мыши, но курсор ОС не двигается, окно поднимать/фокусировать не нужно.
Траектория — короткая квадратичная Безье с шумом (поток mousemove выглядит
живым), скорость и пауза нажатия — как у человеческого клика.
"""

from __future__ import annotations

import math
import random
import time


def human_click(page, cx: float, cy: float, radius: float = 20.0, rng=None) -> None:
    """Клик в CSS-координаты (cx, cy) страницы через CDP.

    radius — половина ширины клетки: точка клика гауссовым сдвигом разбрасывается
    внутри круга радиуса radius/2 (как в физическом MouseController).
    """
    rng = rng or random
    r = max(3.0, radius * 0.5)
    dx, dy = rng.gauss(0, r / 2.0), rng.gauss(0, r / 2.0)
    d = math.hypot(dx, dy)
    if d > r and d > 0:
        dx, dy = dx * r / d, dy * r / d
    tx, ty = cx + dx, cy + dy

    # старт — последняя известная CDP-позиция «мыши» (для непрерывности пути)
    try:
        sx, sy = page.evaluate("() => [window.__c4_mx || 0, window.__c4_my || 0]")
    except Exception:  # noqa: BLE001
        sx, sy = tx, max(0.0, ty - 150.0)
    if not sx and not sy:
        sx, sy = tx, max(0.0, ty - 150.0)

    # квадратичная Безье со срединным выносом (bow), как в физическом плане
    dist = math.hypot(tx - sx, ty - sy)
    bow = rng.uniform(-1.0, 1.0) * max(6.0, dist * 0.12)
    mx, my = (sx + tx) / 2.0, (sy + ty) / 2.0
    nx, ny = -(ty - sy), (tx - sx)
    nl = math.hypot(nx, ny) or 1.0
    c2x, c2y = mx + nx / nl * bow, my + ny / nl * bow

    steps = rng.randint(14, 26)
    for i in range(1, steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * c2x + t ** 2 * tx
        y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * c2y + t ** 2 * ty
        page.mouse.move(x, y)
        time.sleep(rng.uniform(0.004, 0.012))
    try:
        page.evaluate("(p) => { window.__c4_mx = p[0]; window.__c4_my = p[1]; }", [tx, ty])
    except Exception:  # noqa: BLE001
        pass
    page.mouse.down()
    time.sleep(rng.uniform(0.040, 0.075))
    page.mouse.up()
