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
    """Клик в CSS-координаты (cx, cy) страницы через CDP — минимум операций.

    ВАЖНО (найдено на живой серии): каждый page.mouse.* — это round-trip к
    браузеру, под нагрузкой (ponder+браузер) он стоит до ~0.6 с. Пошаговая
    траектория из десятков вызовов растягивала клик до 17-22 с и съедала
    40-секундный лимит хода. Поэтому: точка (гауссов сдвиг внутри клетки) +
    один перелёт (mouse.move со steps) + атомарный click(delay).
    """
    rng = rng or random
    r = max(3.0, radius * 0.5)
    dx, dy = rng.gauss(0, r / 2.0), rng.gauss(0, r / 2.0)
    d = math.hypot(dx, dy)
    if d > r and d > 0:
        dx, dy = dx * r / d, dy * r / d
    tx, ty = cx + dx, cy + dy

    try:
        page.mouse.move(tx, ty, steps=rng.randint(3, 6))
    except Exception:  # noqa: BLE001
        pass
    time.sleep(rng.uniform(0.03, 0.09))
    page.mouse.click(tx, ty, delay=rng.randint(45, 80))
