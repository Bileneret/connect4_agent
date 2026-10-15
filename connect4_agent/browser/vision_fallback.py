"""Экранный фолбек чтения доски: MSS-захват области + классификация по RGB.

Вопросы №2-В и №5: используется, если браузер без CDP (или DOM нечитаем).
Захватывается прямоугольная область доски (физические пиксели экрана),
в центрах клеток берутся пиксели и классифицируются на три класса по эталонным
цветам из config: наши фишки #17B99A, соперника #F16775, фон доски #293441.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import BOARD_BG_RGB, MY_DISK_RGB, OPPONENT_DISK_RGB  # noqa: E402

EMPTY, MINE, OPP = 0, 1, 2


@dataclass
class VisionRegion:
    left: int
    top: int
    width: int
    height: int


class VisionReader:
    """Чтение доски с экрана: сетка ограничивающего прямоугольника -> матрица."""

    def __init__(self, region: VisionRegion, cols: int = 7, rows: int = 6,
                 colors=None):
        self.region = region
        self.cols = cols
        self.rows = rows
        self.colors = colors or {
            EMPTY: np.array(BOARD_BG_RGB, dtype=np.int32),
            MINE: np.array(MY_DISK_RGB, dtype=np.int32),
            OPP: np.array(OPPONENT_DISK_RGB, dtype=np.int32),
        }

    # --- классификация -----------------------------------------------------
    def classify_pixel(self, rgb) -> int:
        """Ближайший эталонный цвет; дальше порога — считаем фоном (0)."""
        px = np.asarray(rgb, dtype=np.int32)[:3]
        best, best_dist = EMPTY, 1 << 30
        for code, ref in self.colors.items():
            d = int(np.abs(px - ref).sum())
            if d < best_dist:
                best, best_dist = code, d
        if best != EMPTY and best_dist > 90:  # ни на что не похоже — фон/тень
            return EMPTY
        return best

    def from_array(self, img: np.ndarray):
        """img: HxWx3 (пиксели области) -> (grid[row][col], heights).

        Каждая клетка читается мульти-сэмплингом (центр + 4 смещённых точки):
        большинство непустых цветов определяет владельца — устойчиво к
        микро-сдвигам сетки относительно лунок.
        """
        h, w = img.shape[:2]
        grid = [[EMPTY] * self.cols for _ in range(self.rows)]
        offsets = ((0.0, 0.0), (-0.18, 0.0), (0.18, 0.0), (0.0, -0.18), (0.0, 0.18))
        for col in range(self.cols):
            for row_vis in range(self.rows):
                votes = {EMPTY: 0, MINE: 0, OPP: 0}
                for ox, oy in offsets:
                    cx = int((col + 0.5 + ox) * w / self.cols)
                    cy = int((row_vis + 0.5 + oy) * h / self.rows)
                    cx = min(max(cx, 0), w - 1)
                    cy = min(max(cy, 0), h - 1)
                    votes[self.classify_pixel(img[cy, cx])] += 1
                # приоритет у непустых цветов: если большинство видит фишку — она там
                winner = EMPTY
                for code in (MINE, OPP):
                    if votes[code] >= 2 or votes[code] >= votes[EMPTY]:
                        if votes[code] > votes[winner]:
                            winner = code
                if votes[EMPTY] == 5:
                    winner = EMPTY
                grid[self.rows - 1 - row_vis][col] = winner
        heights = []
        for col in range(self.cols):
            k = 0
            while k < self.rows and grid[k][col] != EMPTY:
                k += 1
            heights.append(k)
        return grid, heights

    # --- захват ------------------------------------------------------------
    def capture(self, region: "VisionRegion | None" = None) -> np.ndarray:
        """MSS-снимок области (по умолчанию — сохранённой в конструкторе)."""
        from mss import mss

        reg = region or self.region
        with mss() as sct:
            shot = sct.grab({
                "left": reg.left, "top": reg.top,
                "width": reg.width, "height": reg.height,
            })
            img = np.asarray(shot)[:, :, :3]  # BGRA -> BGR
        return img[:, :, ::-1]  # RGB

    def read(self):
        return self.from_array(self.capture())

    # --- поиск доски на кадре (для честного фолбэка без DOM) ---------------
    # Реальный цвет пластины доски на живом сайте (замер 16.10.2026): (45,62,80)
    PLATE_RGB = (45, 62, 80)

    @classmethod
    def _plate_mask(cls, img: np.ndarray) -> np.ndarray:
        r = img[:, :, 0].astype(np.int16)
        g = img[:, :, 1].astype(np.int16)
        b = img[:, :, 2].astype(np.int16)
        pr, pg, pb = cls.PLATE_RGB
        return (np.abs(r - pr) + np.abs(g - pg) + np.abs(b - pb)) <= 30

    @classmethod
    def locate_board(cls, img: np.ndarray):
        """Габариты пластины доски на произвольном кадре: (x, y, w, h) или None.

        Профили строк/столбцов с порогом от максимума отсекают «хвосты» других
        панелей того же цвета (bbox по перцентилям их захватывал).
        """
        mask = cls._plate_mask(img)
        if float(mask.mean()) < 0.02:
            return None
        colprof = mask.sum(axis=0)
        rowprof = mask.sum(axis=1)

        def span(prof):
            thr = prof.max() * 0.35
            idx = np.where(prof >= thr)[0]
            if len(idx) == 0:
                return 0, prof.shape[0] - 1
            return int(idx[0]), int(idx[-1])

        x0, x1 = span(colprof)
        y0, y1 = span(rowprof)
        if x1 - x0 < 50 or y1 - y0 < 50:
            return None
        w, h = x1 - x0, y1 - y0
        # доска 7x6 — пропорции 7/6. Профиль с порогом изредка срезает левую
        # крайнюю колонку, когда её перекрывает реклама/панель (DPI-тест 16.10:
        # w=568 при h=567, истина 663=7*94.5; правый край при этом верен) —
        # тогда восстанавливаем ширину/левый край от надёжных высоты и правого края
        if abs(w / h - 7.0 / 6.0) > 0.06:
            w2 = int(round(h / 6.0 * 7.0))
            x2 = x1 - w2
            if x2 >= 0:
                x0, w = x2, w2
        return x0, y0, w, h

    def locate_and_read(self, img: np.ndarray):
        """Найти доску на кадре и прочитать сетку (розничный режим без DOM)."""
        box = self.locate_board(img)
        if box is None:
            return None, None, None
        x, y, w, h = box
        grid, heights = self.from_array(img[y:y + h, x:x + w])
        return grid, heights, box
