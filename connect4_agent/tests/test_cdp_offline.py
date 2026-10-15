"""Офлайн-тест браузерного слоя Этапа 5 на локальном мок-полигоне.

Сценарий: находится установленный браузер, запускается (headless) с отладочным
портом на мок-странице игры, коннектор находит порт и вкладку, подключается
через CDP и читает документ. Ничего в системе пользователя не меняется.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.cdp_connector import (  # noqa: E402
    connect_tab, find_debug_ports, find_installed_browsers,
    list_tabs, wait_for_port,
)
from _cdp_testutil import prepare_test_browser, teardown_test_browser  # noqa: E402

PORT = 9229  # внутри штатного диапазона коннектора (9222..9229), верхний край
FIXTURE = ROOT / "tests" / "fixtures" / "connect4_mock.html"


def main():
    installed = find_installed_browsers()
    if not installed:
        print("FAIL: не найдено ни одного браузера для теста")
        return 1
    name, exe = sorted(installed.items())[0]
    print(f"браузер для теста: {name} ({exe})")

    proc = prepare_test_browser(exe, PORT, FIXTURE.as_uri(), headless=True)
    try:
        print(f"порт {PORT} открыт (изолированный профиль)")

        ports = find_debug_ports()
        assert PORT in ports, f"живой порт {PORT} не найден коннектором"
        print(f"коннектор видит порты: {ports}")

        tabs = list_tabs(PORT)
        assert tabs, "нет вкладок на порту"
        mock_tab = next((t for t in tabs if "connect4_mock" in t.url), None)
        assert mock_tab is not None, f"мок-вкладка не найдена среди {[t.url for t in tabs]}"
        print(f"найдена вкладка: [{mock_tab.title}] {mock_tab.url[:70]}")

        conn = connect_tab(mock_tab)
        try:
            title = conn.evaluate("document.title")
            cells = conn.evaluate("document.querySelectorAll('#board .cell').length")
            print(f"подключение OK: title={title!r}, клеток на доске: {cells}")

            # игровой сценарий на моке: два клика в разные колонки
            conn.evaluate("""
                const b = document.getElementById('board');
                const click = (col) => {
                    const cell = document.querySelector(`.cell[data-col="${col}"]`);
                    cell.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                };
                click(3); click(2);
            """)
            owners = conn.evaluate("""
                Array.from(document.querySelectorAll('#board .cell'))
                     .filter(c => c.dataset.owner !== '0')
                     .map(c => [c.dataset.col, c.dataset.row, c.dataset.owner])
            """)
            print(f"после двух кликов занятые клетки (col,row,owner): {owners}")
            assert len(owners) == 2, "мок не зафиксировал два хода"
            active = conn.evaluate(
                "document.querySelector('#player-left .avatar').classList.contains('active')")
            print(f"активен наш профиль после двух ходов (должно быть True): {active}")
        finally:
            conn.close()
        print("ОФЛАЙН-ТЕСТ ЭТАПА 5: OK")
        return 0
    finally:
        teardown_test_browser(proc, PORT)


if __name__ == "__main__":
    sys.exit(main())
