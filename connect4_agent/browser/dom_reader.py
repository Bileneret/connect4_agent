"""Чтение состояния игры со страницы одним вызовом page.evaluate — Вопросы №2-№8, №40.

Один снимок возвращает: матрицу доски (кто владелец каждой клетки), высоты
колонок, чья очередь (по активному кольцу/таймеру слева-направо), цифровые
таймеры, геометрию нижних ячеек для физического клика (Q8: клиентские CSS-px +
screenX/Y + DPR) и проверку перекрытия всплывающими окнами (Q7).

Распознавание владельцев — в порядке приоритета:
  1) атрибуты DOM (data-owner / классы) — «логические» селекторы (Q6-А);
  2) цвета: автокалибровка по образцам фишек в шапке (Q6-Б), классификация
     вычисленного background-color с допуском.

Конфиг селекторов вынесен в DefaultSelectors; после встречи с живым
papergames.io сюда будут вписаны его точные селекторы (исследование на месте).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    BOARD_BG_RGB, MY_DISK_RGB, OPPONENT_DISK_RGB, WIDTH, HEIGHT,
)


@dataclass
class Selectors:
    board: str = "#board"
    cell: str = ".cell"
    avatar_active_class: str = "active"
    left_panel: str = "#player-left"
    right_panel: str = "#player-right"


DEFAULT_SELECTORS = Selectors()

# --- живой профиль papergames.io (разведка 16.10.2026) ---------------------
# Доска: div.grid.size6x7; клетки: .grid-item.cell-{R}-{C} где R — ряд
# 1..6 СВЕРХУ ВНИЗ, C — колонка 1..7 СЛЕВА (проверено: cell-1-1 = левый верх,
# фишка на нижнем ряду правой колонки = cell-6-7); фишка = SVG-круг внутри
# клетки БЕЗ класса empty-slot (читать с задержкой >= 1.5 c после хода —
# анимация); наш цвет ~#18BC9C, соперника ~#F16775; активный ход: у
# .chronometer (первый — наш, левая шапка) появляется класс bg-secondary;
# URL комнаты /en/r/<id>; у каждого игрока 4 минуты на партию (блиц).
PAPERGAMES = Selectors(
    board=".grid",
    cell=".grid-item",
    avatar_active_class="bg-secondary",
    left_panel="",
    right_panel="",
)
PAPERGAMES_MY_RGB = (24, 188, 156)      # наш цвет (проверено на живом сайте)
PAPERGAMES_OPP_RGB = (238, 102, 119)    # цвет соперника (живой замер 16.10.2026)

_PAPERGAMES_READ_JS = r"""
(cfg) => {
  let myRgb = cfg.my, oppRgb = cfg.opp;   // dict-аргумент: Playwright иначе
                                          // передал бы список одним параметром
  const rect = el => { const r = el.getBoundingClientRect();
    return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  const parseColor = s => { const m = (s || '').match(/rgba?\(\d+\),\s*(\d+),\s*(\d+)/);
    return m ? [+m[1], +m[2], +m[3]] : null; };
  const dist = (a, b) => a && b ? Math.abs(a[0]-b[0])+Math.abs(a[1]-b[1])+Math.abs(a[2]-b[2]) : 1e9;

  const out = {errors: [], grid: [], heights: [], col_centers: [], board_rect: null,
               moves: 0, my_turn: false, my_side: "left", timers: {},
               dpr: window.devicePixelRatio || 1,
               screen_x: window.screenX, screen_y: window.screenY,
               chrome_top: Math.max(0, window.outerHeight - window.innerHeight),
               covered: []};

  const board = document.querySelector('.grid');
  const cells = Array.from(document.querySelectorAll('.grid-item'));
  if (!board || !cells.length) { out.errors.push('board/cells not found'); return out; }
  out.board_rect = rect(board);

  let W = 7, H = 6;
  const mSize = String(board.className).match(/size(\d+)x(\d+)/);
  if (mSize) { H = +mSize[1]; W = +mSize[2]; }
  out.grid = Array.from({length: H}, () => new Array(W).fill(0));

  // СТОРОНА по нашему нику (в матчмейкинге мы бываем и справа), хронометры
  // сортируем по x; наш ход — активен хронометр НАШЕЙ стороны
  let mySide = "left";
  const nameEl = Array.from(document.querySelectorAll('*')).find(e =>
      e.children.length === 0 && (e.textContent || '').trim() === cfg.my_name
      && e.getBoundingClientRect().top < 140);
  if (nameEl) {
    mySide = nameEl.getBoundingClientRect().left < window.innerWidth / 2 ? "left" : "right";
  }
  out.my_side = mySide;
  const chronos = Array.from(document.querySelectorAll('.chronometer'))
      .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
  out.timers = {};
  if (chronos[0]) out.timers.left = chronos[0].textContent.trim();
  if (chronos[1]) out.timers.right = chronos[1].textContent.trim();
  const ourChrono = chronos[mySide === "left" ? 0 : 1];
  const theirChrono = chronos[mySide === "left" ? 1 : 0];
  if (ourChrono) out.my_turn = ourChrono.classList.contains('bg-secondary');

  // цвета-индикаторы: насыщенные кружки-точки рядом с хронометрами
  const dots = [];
  for (const e of document.querySelectorAll('*')) {
    const r = e.getBoundingClientRect();
    if (r.top > 140 || r.width < 8 || r.width > 46 || Math.abs(r.width - r.height) > 8) continue;
    const c = parseColor(getComputedStyle(e).backgroundColor);
    if (!c) continue;
    if (Math.max(c[0], c[1], c[2]) - Math.min(c[0], c[1], c[2]) < 40) continue;
    dots.push({c: c, x: r.x + r.width / 2, y: r.y + r.height / 2});
  }
  const dotNear = (chron) => {
    if (!chron) return null;
    const r = chron.getBoundingClientRect();
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    let best = null, bd = 1e9;
    for (const d of dots) {
      const dd = Math.hypot(d.x - cx, (d.y - cy) * 1.5);
      if (dd < bd) { bd = dd; best = d; }
    }
    return bd <= 170 ? best.c : null;
  };
  const ourDot = dotNear(ourChrono);
  const theirDot = dotNear(theirChrono);
  if (ourDot) myRgb = ourDot;
  if (theirDot) oppRgb = theirDot;

  // клетки: владелец по цвету фишки (калиброванные цвета выше)
  const colCells = new Map();
  for (const c of cells) {
    const m = String(c.className).match(/cell-(\d+)-(\d+)/);
    if (!m) continue;
    const row1 = +m[1], col1 = +m[2];      // cell-{R}-{C}: R 1..6 сверху, C 1..7 слева
    const col = col1 - 1;
    const rowBottom0 = H - row1;
    const circles = Array.from(c.querySelectorAll('circle'));
    const pieceCircle = circles.find(k => !k.classList.contains('empty-slot'));
    if (pieceCircle) {
      const fill = parseColor(getComputedStyle(pieceCircle).fill) ||
                   parseColor(pieceCircle.getAttribute('fill'));
      if (dist(fill, myRgb) <= 120) out.grid[rowBottom0][col] = 1;
      else if (dist(fill, oppRgb) <= 120) out.grid[rowBottom0][col] = 2;
      else out.errors.push('unknown disc color ' + JSON.stringify(fill) +
                           ' my=' + JSON.stringify(myRgb) + ' opp=' + JSON.stringify(oppRgb));
    }
    if (!colCells.has(col)) colCells.set(col, []);
    colCells.get(col).push(c);
  }
  let moves = 0;
  for (const row of out.grid) for (const v of row) if (v) moves++;
  out.moves = moves;
  for (let c = 0; c < W; c++) {
    let h = 0; while (h < H && out.grid[h][c]) h++;
    out.heights.push(h);
  }

  // центры нижних ячеек колонок + проверка перекрытия
  for (let c = 0; c < W; c++) {
    const list = colCells.get(c) || [];
    if (!list.length) { out.col_centers.push(null); out.covered.push(true); continue; }
    const bottom = list.reduce((a, b) => rect(a).y > rect(b).y ? a : b);
    const r = rect(bottom);
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    out.col_centers.push([cx, cy]);
    const top = document.elementFromPoint(cx, cy);
    out.covered.push(!(top === bottom || bottom.contains(top) || board.contains(top)));
  }
  return out;
}
"""


UNKNOWN_RETRY_DELAY_S = 0.2   # P1.4: пауза перед повтором при транзиенте анимации


def read_papergames(page, retry_on_unknown: bool = True) -> BoardSnapshot:
    """Снимок живой доски papergames.io (селекторы разведаны 16.10.2026).

    P1.4: у только что упавшей фишки fill может быть ещё null (анимация) —
    транзиент «unknown disc color» лечится одним повтором чтения через ~200 мс.
    """
    snap = _read_papergames_once(page)
    if (retry_on_unknown
            and any(e.startswith("unknown disc color") for e in snap.raw_errors)):
        time.sleep(UNKNOWN_RETRY_DELAY_S)
        return _read_papergames_once(page)
    return snap


def _read_papergames_once(page) -> BoardSnapshot:
    from config import PLAYER_NAME

    data = page.evaluate(_PAPERGAMES_READ_JS,
                         {"my": list(PAPERGAMES_MY_RGB), "opp": list(PAPERGAMES_OPP_RGB),
                          "my_name": PLAYER_NAME})
    return BoardSnapshot(
        grid=data["grid"],
        heights=data["heights"],
        moves=data["moves"],
        my_turn=data["my_turn"],
        active_side="left" if data["my_turn"] else "right",
        timers=data["timers"],
        col_centers_client=data["col_centers"],
        board_rect=data["board_rect"],
        dpr=data["dpr"],
        screen_x=data["screen_x"],
        screen_y=data["screen_y"],
        chrome_top_px=data["chrome_top"],
        covered=data["covered"],
        raw_errors=data.get("errors", []),
    )


@dataclass
class BoardSnapshot:
    grid: list[list[int]]           # grid[row][col]: 0 пусто, 1 наши, 2 соперник (row 0 = низ)
    heights: list[int]
    moves: int
    my_turn: bool                   # очередь ходить у нас (активен левый профиль)
    active_side: str                # "left" | "right" | "none"
    timers: dict
    col_centers_client: list        # [(x, y)] центр нижней ячейки каждой колонки, CSS px от вьюпорта
    board_rect: dict
    dpr: float
    screen_x: float
    screen_y: float
    chrome_top_px: float            # outerHeight - innerHeight: высота UI браузера над вьюпортом
    covered: list                   # covered[col] = True, если центр нижней ячейки перекрыт не-доской (Q7)
    raw_errors: list = field(default_factory=list)

    def col_center_screen_px(self, col: int) -> tuple[float, float]:
        """Экранные ФИЗИЧЕСКИЕ пиксели центра нижней ячейки колонки (best effort, Q8).

        Проверка на живой странице с учётом Windows DPI — на этапе интеграции.
        """
        cx, cy = self.col_centers_client[col]
        css_x = self.screen_x + cx
        css_y = self.screen_y + self.chrome_top_px + cy
        return css_x * self.dpr, css_y * self.dpr


_READ_JS = r"""
(cfg) => {
  const out = {grid: null, heights: null, moves: 0, active_side: "none", timers: {},
               col_centers: [], board_rect: null, dpr: window.devicePixelRatio || 1,
               screen_x: window.screenX, screen_y: window.screenY,
               chrome_top: Math.max(0, window.outerHeight - window.innerHeight),
               covered: [], errors: []};

  const parseRgb = (s) => {
    const m = s && s.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    return m ? [ +m[1], +m[2], +m[3] ] : null;
  };
  const dist = (a, b) => a && b ? Math.abs(a[0]-b[0]) + Math.abs(a[1]-b[1]) + Math.abs(a[2]-b[2]) : 1e9;

  const board = document.querySelector(cfg.board);
  if (!board) { out.errors.push("board not found: " + cfg.board); return out; }
  const rect = board.getBoundingClientRect();
  out.board_rect = {x: rect.x, y: rect.y, w: rect.width, h: rect.height};

  const cells = Array.from(board.querySelectorAll(cfg.cell));
  if (!cells.length) { out.errors.push("no cells"); return out; }

  // сетка из data-атрибутов; иначе — геометрическая раскладка
  let W = 0, H = 0;
  const byRC = new Map();
  for (const c of cells) {
    const col = c.dataset.col !== undefined ? +c.dataset.col : null;
    const row = c.dataset.row !== undefined ? +c.dataset.row : null;
    if (col === null || row === null) { byRC.clear(); break; }
    byRC.set(row + ":" + col, c);
    W = Math.max(W, col + 1); H = Math.max(H, row + 1);
  }
  if (!byRC.size) { out.errors.push("cells without row/col attributes"); return out; }

  // образцы цветов из шапки (калибровка, Q6-Б)
  const sampleOf = (sel) => {
    const el = document.querySelector(cfg.left_panel + " " + sel);
    return el ? parseRgb(getComputedStyle(el).backgroundColor) : null;
  };
  const myColor = sampleOf(".disk-sample") || null;   // по умолчанию мок: первый disk-sample слева
  const oppColor = (() => {
    const el = document.querySelector(cfg.right_panel + " .disk-sample");
    return el ? parseRgb(getComputedStyle(el).backgroundColor) : null;
  })();

  const owners = new Map();
  const colorVotes = [];
  for (const [rc, c] of byRC) {
    let owner = 0;
    const attr = c.dataset.owner;
    if (attr !== undefined) owner = +attr | 0;
    else {
      const bg = parseRgb(getComputedStyle(c).backgroundColor);
      if (bg && dist(bg, myColor) < 40) owner = 1;
      else if (bg && dist(bg, oppColor) < 40) owner = 2;
      else if (bg) colorVotes.push(bg);
    }
    owners.set(rc, owner);
  }
  out.grid = Array.from({length: H}, (_, r) =>
      Array.from({length: W}, (_, c) => owners.get(r + ":" + c) || 0));
  for (let r = 0; r < H; r++) for (let c = 0; c < W; c++) if (out.grid[r][c]) out.moves++;
  out.heights = Array.from({length: W}, (_, c) => {
    let h = 0; while (h < H && out.grid[h][c]) h++; return h;
  });

  // чья очередь: активная отметка у левой (нашей) или правой панели
  const isActive = (panelSel) => {
    const p = document.querySelector(panelSel);
    if (!p) return false;
    return !!p.querySelector("." + cfg.active_class) ||
           Array.from(p.querySelectorAll("*")).some(e => e.classList.contains(cfg.active_class));
  };
  out.active_side = isActive(cfg.left_panel) ? "left"
                  : isActive(cfg.right_panel) ? "right" : "none";
  for (const side of ["left", "right"]) {
    const t = document.querySelector((side === "left" ? cfg.left_panel : cfg.right_panel)
                                     + " .timer");
    if (t) out.timers[side] = t.textContent.trim();
  }

  // геометрия нижних ячеек каждой колонки (клиентские CSS px) + проверка перекрытия
  for (let c = 0; c < W; c++) {
    const bottom = byRC.get("0:" + c) || byRC.get("0:" + c);
    if (!bottom) { out.col_centers.push(null); out.covered.push(true); continue; }
    const r = bottom.getBoundingClientRect();
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    out.col_centers.push([cx, cy]);
    const top = document.elementFromPoint(cx, cy);
    out.covered.push(!(top === bottom || board.contains(top)));
  }
  return out;
}
"""


def read_state(page, selectors: Selectors = DEFAULT_SELECTORS) -> BoardSnapshot:
    """Снять состояние доски со страницы (одно evaluate)."""
    data = page.evaluate(_READ_JS, {
        "board": selectors.board,
        "cell": selectors.cell,
        "left_panel": selectors.left_panel,
        "right_panel": selectors.right_panel,
        "active_class": selectors.avatar_active_class,
    })
    return BoardSnapshot(
        grid=data["grid"],
        heights=data["heights"],
        moves=data["moves"],
        my_turn=data["active_side"] == "left",
        active_side=data["active_side"],
        timers=data["timers"],
        col_centers_client=data["col_centers"],
        board_rect=data["board_rect"],
        dpr=data["dpr"],
        screen_x=data["screen_x"],
        screen_y=data["screen_y"],
        chrome_top_px=data["chrome_top"],
        covered=data["covered"],
        raw_errors=data.get("errors", []),
    )


def from_grid(grid: list[list[int]], my_turn: bool):
    """Q16: (position, mask, moves) прямо из матрицы владельцев (row 0 = низ).

    position — камни игрока, чья очередь (определяется флагом my_turn);
    mask — все камни; кодировка колонок: бит c*7 + r (сигнальный ряд сверху).
    История ходов не требуется — это и есть восстановление с любого момента.
    """
    import numpy as np

    h1 = HEIGHT + 1
    mask = 0
    position = 0
    moves = 0
    mover_owner = 1 if my_turn else 2   # камни ходящего: наши (1) или соперника (2)
    for r, row in enumerate(grid):
        for c, owner in enumerate(row):
            if owner:
                bit = 1 << (c * h1 + r)
                mask |= bit
                moves += 1
                if owner == mover_owner:
                    position |= bit
    return np.uint64(position), np.uint64(mask), moves


def grid_from_snapshot(snapshot: BoardSnapshot):
    """Совместимость: (position, mask, moves) из снимка страницы."""
    return from_grid(snapshot.grid, snapshot.my_turn)
