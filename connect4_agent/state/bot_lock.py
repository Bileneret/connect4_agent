"""PID-локфайл живого бота — защита от параллельных CDP-скриптов (P1.3).

Инцидент 16.10.2026: recon-скрипт, запущенный во время боя бота, нажал Resign
в его партии. Теперь `run.py --live` держит `logs/bot.lock` (PID + порт + время
старта), «вмешивающиеся» инструменты (recon/probe/verify/...) при живом боте
отказываются работать без `--force`, а «совместные» (серия приёмки, друг,
вход в робо-игру) — наоборот, требуют живого бота.

Проверка живости PID: Windows — OpenProcess + GetExitCodeProcess (STILL_ACTIVE);
отказ доступа трактуется как «жив» (безопасная сторона). Мёртвый PID при чтении
означает локфайл-сироту и удаляется.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "logs" / "bot.lock"

_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


class BotAlreadyRunning(RuntimeError):
    """Живой бот уже держит локфайл."""


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        access = 0x00100000 | 0x1000  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            # нет прав на чтение чужого процесса — считаем живым (безопаснее)
            return kernel32.GetLastError() == _ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def bot_running() -> dict | None:
    """Инфо о живом боте или None; локфайл-сирота (мёртвый PID) удаляется."""
    try:
        info = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        pid = int(info.get("pid") or 0)
    except (OSError, ValueError):
        return None
    if pid and _pid_alive(pid):
        return info
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def describe(info: dict) -> str:
    return (f"PID {info.get('pid', '?')}, порт {info.get('port', '?')}, "
            f"старт {info.get('started', '?')}")


def acquire(port: int | None = None, mode: str = "live") -> dict:
    """Захватить локфайл; при живом боте в локфайле — BotAlreadyRunning."""
    existing = bot_running()
    if existing is not None:
        raise BotAlreadyRunning(
            f"живой бот уже запущен ({describe(existing)}) — второй экземпляр не нужен")
    info = {"pid": os.getpid(), "port": port, "mode": mode,
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def release() -> None:
    """Снять локфайл — только если он наш (по PID); чужой не трогаем."""
    try:
        info = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if int(info.get("pid") or 0) == os.getpid():
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass


def ensure_no_bot(tool: str, force: bool = False) -> None:
    """Для вмешивающихся инструментов: стоп (exit 3), если бот жив."""
    info = bot_running()
    if info is None or force:
        return
    print(f"[{tool}] ОТКАЗ: живой бот уже работает ({describe(info)}).\n"
          f"[{tool}] Этот инструмент вмешивается в страницу и может испортить партию.\n"
          f"[{tool}] Остановите бота (Esc в его консоли) или повторите с --force.")
    sys.exit(3)


def ensure_bot(tool: str, force: bool = False) -> None:
    """Для совместных инструментов (серия, друг, вход в робо-игру): нужен бот."""
    if bot_running() is not None or force:
        return
    print(f"[{tool}] ОТКАЗ: живой бот не найден (нет {LOCK_PATH.name} "
          f"или PID в нём мёртв).\n"
          f"[{tool}] Инструмент задуман для совместной работы с run.py --live.\n"
          f"[{tool}] Запустите бота или повторите с --force.")
    sys.exit(3)
