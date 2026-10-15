"""Утилиты изоляции тестовых браузеров: выделенный профиль + зачистка зависших.

Проблема, которую решают: запуск Edge/Chrome с дефолтным профилем, когда уже
есть живой экземпляр, форвардит аргументы ему — рождается НЕ наш процесс, порт
уже занят старым браузером, а terminate() убивает лишь пустышку-лаунчер.
Решение: тестовый запуск всегда с --user-data-dir=<отдельная папка>, плюс
перед запуском зачищаются процессы с нашим отладочным портом в командной строке.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "tests" / "fixtures" / "_cdp_test_profile"


def kill_stale_cdp_browsers(port: int):
    """Убить деревья процессов, у которых в командной строке наш отладочный порт."""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe' "
        "or Name='brave.exe'\" | "
        f"Where-Object {{$_.CommandLine -like '*remote-debugging-port={port}*'}} | "
        "ForEach-Object { taskkill /F /T /PID $_.ProcessId }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30)


def prepare_test_browser(exe: str, port: int, url: str, headless=True, extra=None):
    """Чистый тестовый запуск браузера с изолированным профилем."""
    from browser.cdp_connector import launch_browser, wait_for_port

    kill_stale_cdp_browsers(port)
    time.sleep(0.5)
    shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    flags = [f"--user-data-dir={PROFILE_DIR}", "--no-first-run",
             "--no-default-browser-check", "--window-size=1400,1100"]
    if extra:
        flags.extend(extra)
    proc = launch_browser(exe, port, url=url, headless=headless, extra_flags=flags)
    if not wait_for_port(port, timeout=30):
        raise RuntimeError(f"тестовый браузер не открыл порт {port}")
    return proc


def teardown_test_browser(proc, port: int):
    """Гарантированная зачистка: и наш процесс, и всё, что осталось на порту."""
    try:
        proc.terminate()
    except Exception:
        pass
    kill_stale_cdp_browsers(port)
