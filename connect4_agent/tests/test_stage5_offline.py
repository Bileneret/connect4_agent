"""Офлайн-тест всего браузерного слоя Этапа 5 на мок-полигоне:

  1) vision_fallback — классификация синтетической картинки доски;
  2) dom_reader — снимок доски/очереди/геометрии + сверка битбордов с движком;
  3) dom_reader по цветам — после снятия data-атрибутов (путь автокалибровки Q6-Б);
  4) overlay — метки оценок, подсветка, клик мышью СКВОЗЬ оверлей.
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser import overlay  # noqa: E402
from browser.cdp_connector import (  # noqa: E402
    connect_tab, find_installed_browsers, list_tabs, wait_for_port,
)
from _cdp_testutil import prepare_test_browser, teardown_test_browser  # noqa: E402
from browser.dom_reader import from_grid, read_state  # noqa: E402
from browser.vision_fallback import (  # noqa: E402
    EMPTY, MINE, OPP, VisionReader, VisionRegion,
)
from config import BOARD_BG_RGB, MY_DISK_RGB, OPPONENT_DISK_RGB  # noqa: E402
from engine.bitboard import load_position  # noqa: E402

PORT = 9229
FIXTURE = ROOT / "tests" / "fixtures" / "connect4_mock.html"


def test_vision():
    cell = 84
    cols, rows = 7, 6
    img = np.zeros((rows * cell, cols * cell, 3), dtype=np.uint8)
    img[:, :] = BOARD_BG_RGB
    heights = [0, 1, 2, 0, 1, 0, 0]
    owner_colors = {MINE: MY_DISK_RGB, OPP: OPPONENT_DISK_RGB}
    owners = {1: MINE, 2: OPP, 4: MINE}
    for c, k in enumerate(heights):
        for r in range(k):
            img[(rows - 1 - r) * cell:(rows - r) * cell, c * cell:(c + 1) * cell] = \
                owner_colors[owners.get(c, MINE)]
    vr = VisionReader(VisionRegion(0, 0, cols * cell, rows * cell))
    grid, got_heights = vr.from_array(img)
    assert got_heights == heights, f"высоты {got_heights} != {heights}"
    assert grid[0][2] == OPP and grid[0][4] == MINE, "владелец нижней клетки не распознан"
    assert grid[1][2] == OPP, "второй этаж колонки 2 не распознан"
    print("  vision_fallback: OK (синтетическая доска распознана)")


def main():
    test_vision()

    installed = find_installed_browsers()
    exe = sorted(installed.items())[0][1]
    proc = prepare_test_browser(exe, PORT, FIXTURE.as_uri(), headless=True)
    try:
        tabs = [t for t in list_tabs(PORT) if "connect4_mock" in t.url]
        assert tabs, "мок-вкладка не найдена"
        conn = connect_tab(tabs[0])
        page = conn.page
        try:
            # доска целиком во вьюпорте (иначе elementFromPoint даст «перекрыто»)
            page.evaluate(
                "() => { const r = document.getElementById('board').getBoundingClientRect();"
                " window.scrollTo(0, window.scrollY + r.top - 80); }")
            page.evaluate("""
                () => {
                  const click = (c) => document.querySelector(
                      `.cell[data-col="${c}"]`).dispatchEvent(
                      new MouseEvent('click', {bubbles: true}));
                  click(3); click(3); click(2); click(4); click(4);
                }
            """)
            snap = read_state(page)
            assert snap.moves == 5, f"moves={snap.moves}"
            assert snap.heights == [0, 0, 1, 2, 2, 0, 0], snap.heights
            assert snap.active_side == "right" and not snap.my_turn, snap.active_side
            assert snap.timers, "таймеры не прочитаны"
            assert not any(snap.covered), f"ложное перекрытие: {snap.covered}"

            pos, mask, mv = from_grid(snap.grid, snap.my_turn)
            ep, em, emv = load_position("44355")
            assert (int(pos), int(mask), mv) == (int(ep), int(em), emv), (
                f"битборды не сошлись: {int(pos):b}/{int(mask):b} vs {int(ep):b}/{int(em):b}")
            print("  dom_reader: OK (битборды совпали с движком на '44355')")

            page.evaluate(
                "() => document.querySelectorAll('.cell').forEach(c => c.removeAttribute('data-owner'))")
            snap2 = read_state(page)
            assert snap2.moves == 5 and snap2.heights == snap.heights, \
                "цветовая классификация (Q6-Б) не сработала"
            print("  dom_reader по цветам (без data-атрибутов): OK")

            overlay.inject(page, snap.board_rect, [3, -1, 0, 7, 0, -1, -3], best_col=3)
            assert overlay.is_present(page), "оверлей не появился"
            texts = page.evaluate(
                "() => Array.from(document.querySelectorAll("
                "'#__c4_overlay__ div[data-col]')).map(d => d.textContent)")
            assert texts[3] == "WIN +7" and texts[1] == "LOSS -1" and texts[2] == "DRAW 0", texts
            print(f"  overlay: метки {texts}")

            cx, cy = snap.col_centers_client[5]
            page.mouse.click(cx, cy)   # физический клик через CDP по нижней клетке
            snap3 = read_state(page)
            assert snap3.moves == 6 and snap3.heights[5] == 1, \
                f"клик сквозь оверлей не прошёл: moves={snap3.moves}, heights={snap3.heights}"
            print("  overlay: клик мышью СКВОЗЬ оверлей доходит до доски: OK")

            overlay.clear(page)
            assert not overlay.is_present(page), "оверлей не убирается"
            print("  overlay: снятие: OK")
        finally:
            conn.close()
    finally:
        teardown_test_browser(proc, PORT)

    print("ЭТАП 5 — ОФЛАЙН-ЧАСТЬ: ВСЁ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
