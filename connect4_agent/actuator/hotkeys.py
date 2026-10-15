"""Глобальные горячие клавиши и диспетчер режимов — Вопрос №47.

F7 — переключение Auto/Hint, F8 — пауза/продолжить, F9 — ресинк с экрана,
Esc — завершение. Хуки ставятся библиотекой `keyboard` только в register();
в тестах используется диспетчер без установки хуков (dry).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    HOTKEY_EXIT, HOTKEY_PAUSE, HOTKEY_RESYNC, HOTKEY_TOGGLE_MODE,
)

KEYMAP = {
    HOTKEY_TOGGLE_MODE.lower(): "toggle_mode",
    HOTKEY_PAUSE.lower(): "pause",
    HOTKEY_RESYNC.lower(): "resync",
    HOTKEY_EXIT.lower(): "exit",
}


class HotkeyDispatcher:
    """Раскладка клавиш -> обработчики; установка хуков отдельным шагом."""

    def __init__(self):
        self.handlers: dict[str, Callable] = {}
        self._hooks = []

    def bind(self, name: str, handler: Callable):
        self.handlers[name] = handler

    def handle(self, key: str):
        """Вызвать обработчик по имени клавиши (для тестов и своего цикла)."""
        action = KEYMAP.get(key.lower())
        if action and action in self.handlers:
            self.handlers[action]()
            return action
        return None

    def register(self):
        """Поставить глобальные хуки (требует живой сессии Windows)."""
        import keyboard

        for key, action in KEYMAP.items():
            if action in self.handlers:
                self._hooks.append(keyboard.add_hotkey(key, self.handlers[action]))

    def unregister(self):
        import keyboard

        for hook in self._hooks:
            keyboard.remove_hotkey(hook)
        self._hooks = []
