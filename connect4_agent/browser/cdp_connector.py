"""Подключение к браузеру пользователя через CDP — Вопросы №1, №37, №38.

Модуль не создаёт «свой» браузер и не трогает профиль: он ищет уже открытые
отладочные порты (9222..9229), находит установленные браузеры, умеет запустить
выбранный с флагами подавления фонового троттлинга, выводит нумерованный список
вкладок (вкладки papergames.io подсвечиваются) и подключается к выбранной через
Playwright connect_over_cdp — в живой авторизованной сессии пользователя.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import CDP_PORT_RANGE, TARGET_URL_HINT  # noqa: E402

THROTTLE_FLAGS = [
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
]

_BROWSER_CANDIDATES = {
    "chrome": [
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "opera": [
        r"%LocalAppData%\Programs\Opera\launcher.exe",
        r"%ProgramFiles%\Opera\launcher.exe",
    ],
    "yandex": [
        r"%LocalAppData%\Yandex\YandexBrowser\Application\browser.exe",
        r"%ProgramFiles%\Yandex\YandexBrowser\Application\browser.exe",
    ],
}


@dataclass
class TabInfo:
    target_id: str
    title: str
    url: str
    port: int

    @property
    def is_target_site(self) -> bool:
        return TARGET_URL_HINT in self.url


@dataclass
class ConnectedTab:
    page: object          # playwright.sync_api.Page
    browser: object       # playwright Browser (через CDP)
    pw: object            # sync_playwright контекст-менеджер (для закрытия)
    info: TabInfo

    def evaluate(self, script: str):
        return self.page.evaluate(script)

    def close(self):
        """Отключиться от браузера (сам браузер пользователя НЕ закрывается)."""
        try:
            self.browser.close()
        finally:
            self.pw.stop()


def find_installed_browsers() -> dict[str, str]:
    """Установленные браузеры: имя -> путь к exe (расширяет переменные среды)."""
    found = {}
    for name, paths in _BROWSER_CANDIDATES.items():
        for raw in paths:
            p = Path(os.path.expandvars(raw))
            if p.is_file():
                found[name] = str(p)
                break
    return found


def _http_json(url: str, timeout=1.5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def find_debug_ports() -> list[int]:
    """Порты, на которых отвечает CDP /json/version."""
    live = []
    for port in CDP_PORT_RANGE:
        if _http_json(f"http://127.0.0.1:{port}/json/version") is not None:
            live.append(port)
    return live


def list_tabs(port: int) -> list[TabInfo]:
    """Все вкладки (page-таргеты) на отладочном порту."""
    data = _http_json(f"http://127.0.0.1:{port}/json/list")
    if not data:
        return []
    tabs = []
    for t in data:
        if t.get("type") == "page" and not t.get("url", "").startswith("devtools://"):
            tabs.append(TabInfo(t.get("id", ""), t.get("title", ""), t.get("url", ""), port))
    return tabs


def launch_browser(exe: str, port: int, url: str = "about:blank",
                   headless: bool = False, extra_flags=None) -> subprocess.Popen:
    """Запустить браузер с отладочным портом (Вопрос №38: флаги троттлинга).

    Внимание: если экземпляр этого браузера уже запущен без порта отладки,
    Chrome/Edge передадут аргументы существующему процессу и порт НЕ откроется —
    пользователь должен полностью закрыть браузер перед запуском.
    """
    cmd = [exe, f"--remote-debugging-port={port}", *THROTTLE_FLAGS]
    if headless:
        cmd.append("--headless=new")
    if extra_flags:
        cmd.extend(extra_flags)
    cmd.append(url)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_port(port: int, timeout=20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _http_json(f"http://127.0.0.1:{port}/json/version") is not None:
            return True
        time.sleep(0.3)
    return False


def print_tabs(tabs: list[TabInfo]):
    for i, t in enumerate(tabs, 1):
        mark = "  <<< ЦЕЛЬ" if t.is_target_site else ""
        title = (t.title or "(без заголовка)")[:60]
        print(f"  [{i:2d}] порт {t.port} | {title} | {t.url[:80]}{mark}")


def connect_tab(tab: TabInfo, headless_playwright=True) -> ConnectedTab:
    """Подключиться к конкретной вкладке через Playwright CDP."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{tab.port}")
        for context in browser.contexts:
            for page in context.pages:
                if page.url == tab.url or tab.title in (page.title() or ""):
                    return ConnectedTab(page=page, browser=browser, pw=pw, info=tab)
        # запасной вариант: первая страница
        for context in browser.contexts:
            if context.pages:
                return ConnectedTab(page=context.pages[0], browser=browser, pw=pw, info=tab)
        raise RuntimeError("на порту нет доступных страниц")
    except Exception:
        pw.stop()
        raise


def choose_and_connect(interactive=True) -> ConnectedTab | None:
    """Полный сценарий выбора: порты -> вкладки -> подключение.

    interactive=True — пользователь выбирает вкладку номером; иначе
    автоматически берётся вкладка papergames.io (если она одна).
    """
    ports = find_debug_ports()
    if not ports:
        print("Открытых отладочных портов CDP не найдено.")
        installed = find_installed_browsers()
        if not installed:
            print("Установленные Chrome/Edge/Brave/Opera/Yandex не найдены.")
            return None
        print("Установленные браузеры: " + ", ".join(sorted(installed)))
        print("Закройте браузер полностью и запустите его заново с портом отладки:")
        for name, exe in installed.items():
            print(f'  {name}: "{exe}" --remote-debugging-port=9222')
        return None

    tabs = []
    for port in ports:
        tabs.extend(list_tabs(port))
    if not tabs:
        print("На отладочных портах нет вкладок-страниц.")
        return None

    print("Открытые вкладки:")
    print_tabs(tabs)
    target_tabs = [t for t in tabs if t.is_target_site]
    if not interactive:
        if len(target_tabs) == 1:
            return connect_tab(target_tabs[0])
        print("Целевых вкладок не одна — требуется интерактивный выбор.")
        return None
    if len(target_tabs) == 1:
        print(f"Автовыбор единственной вкладки {TARGET_URL_HINT}: [{target_tabs[0].title}]")
        return connect_tab(target_tabs[0])
    choice = input("Номер вкладки (Enter — отмена): ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(tabs):
        print("Отменено.")
        return None
    return connect_tab(tabs[int(choice) - 1])


if __name__ == "__main__":
    conn = choose_and_connect(interactive=True)
    if conn:
        print(f"Подключено: {conn.info.title} | {conn.info.url}")
        print("title из страницы:", conn.evaluate("document.title"))
        conn.close()
