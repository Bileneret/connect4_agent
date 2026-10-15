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
        """img: HxWx3 (пиксели области) -> (grid[row][col], heights)."""
        h, w = img.shape[:2]
        grid = [[EMPTY] * self.cols for _ in range(self.rows)]
        for col in range(self.cols):
            cx = int((col + 0.5) * w / self.cols)
            for row_vis in range(self.rows):
                # визуальный ряд сверху вниз: верхняя строка = высокий ряд
                cy = int((row_vis + 0.5) * h / self.rows)
                code = self.classify_pixel(img[cy, cx])
                grid[self.rows - 1 - row_vis][col] = code
        heights = []
        for col in range(self.cols):
            k = 0
            while k < self.rows and grid[k][col] != EMPTY:
                k += 1
            heights.append(k)
        return grid, heights

    # --- захват ------------------------------------------------------------
    def capture(self) -> np.ndarray:
        """MSS-снимок области (без курсора), BGR -> RGB."""
        from mss import mss

        with mss() as sct:
            shot = sct.grab({
                "left": self.region.left, "top": self.region.top,
                "width": self.region.width, "height": self.region.height,
            })
            img = np.asarray(shot)[:, :, :3]  # BGRA -> BGR
        return img[:, :, ::-1]  # RGB

    def read(self):
        return self.from_array(self.capture())
