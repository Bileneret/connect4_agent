"""Офлайн-тесты итерации И1: локфайл бота (P1.3) и retry чтения доски (P1.4).

Без браузера: локфайл подменяется на временный путь, страница — фейк с
заготовленными ответами evaluate.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser import dom_reader  # noqa: E402
from browser.dom_reader import read_papergames  # noqa: E402
from state import bot_lock  # noqa: E402


def _tmp_lock() -> Path:
    return Path(tempfile.mkdtemp(prefix="c4lock_")) / "bot.lock"


def _exit_code(fn) -> int:
    try:
        fn()
    except SystemExit as exc:
        return exc.code
    return 0


# --- P1.3: локфайл -----------------------------------------------------------

def test_lock_lifecycle():
    real = bot_lock.LOCK_PATH
    bot_lock.LOCK_PATH = _tmp_lock()
    try:
        assert bot_lock.bot_running() is None
        info = bot_lock.acquire(port=9222)
        assert info["pid"] == os.getpid()
        assert bot_lock.bot_running() is not None
        try:
            bot_lock.acquire(port=9223)
            raise AssertionError("повторный acquire должен был упасть")
        except bot_lock.BotAlreadyRunning:
            pass
        bot_lock.release()
        assert bot_lock.bot_running() is None
    finally:
        bot_lock.LOCK_PATH = real


def test_lock_stale_cleanup():
    real = bot_lock.LOCK_PATH
    lock = _tmp_lock()
    bot_lock.LOCK_PATH = lock
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        # 999999999 не кратен 4 -> невалидный Windows-PID, OpenProcess его отвергнет
        lock.write_text(json.dumps({"pid": 999999999, "port": None}), encoding="utf-8")
        assert bot_lock.bot_running() is None
        assert not lock.exists(), "локфайл-сирота с мёртвым PID должен быть удалён"
    finally:
        bot_lock.LOCK_PATH = real


def test_ensure_guards():
    real = bot_lock.LOCK_PATH
    lock = _tmp_lock()
    bot_lock.LOCK_PATH = lock
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.write_text(json.dumps({"pid": os.getpid(), "port": 9222}), encoding="utf-8")
        # «бот жив» (это наш процесс): вмешивающийся инструмент отказывает (exit 3)
        assert _exit_code(lambda: bot_lock.ensure_no_bot("t")) == 3
        bot_lock.ensure_no_bot("t", force=True)   # --force проходит
        bot_lock.ensure_bot("t")                  # совместный при живом боте проходит
        lock.unlink()
        # бота нет: совместный отказывает (exit 3), вмешивающийся проходит
        assert _exit_code(lambda: bot_lock.ensure_bot("t")) == 3
        bot_lock.ensure_bot("t", force=True)
        assert _exit_code(lambda: bot_lock.ensure_no_bot("t")) == 0
    finally:
        bot_lock.LOCK_PATH = real


# --- P1.4: retry чтения при транзиенте анимации -------------------------------

BASE_DATA = {
    "grid": [[0] * 7 for _ in range(6)],
    "heights": [0] * 7, "moves": 0, "my_turn": False, "timers": {},
    "col_centers": [None] * 7, "board_rect": {"x": 0, "y": 0, "w": 70, "h": 60},
    "dpr": 1.0, "screen_x": 0, "screen_y": 0, "chrome_top": 0,
    "covered": [False] * 7, "errors": [],
}


class FakePage:
    def __init__(self, reads):
        self.reads = reads
        self.calls = 0

    def evaluate(self, js, arg=None):
        self.calls += 1
        return self.reads[min(self.calls - 1, len(self.reads) - 1)]


def _no_delay():
    old = dom_reader.UNKNOWN_RETRY_DELAY_S
    dom_reader.UNKNOWN_RETRY_DELAY_S = 0.0
    return old


def test_retry_on_unknown_color():
    transient = dict(BASE_DATA)
    transient["errors"] = ["unknown disc color null my=[24,188,156] opp=[238,102,119]"]
    clean = dict(BASE_DATA)
    clean["grid"] = [[1, 0, 0, 0, 0, 0, 0]] + [[0] * 7 for _ in range(5)]
    clean["heights"] = [1, 0, 0, 0, 0, 0, 0]
    clean["moves"] = 1
    page = FakePage([transient, clean])
    old = _no_delay()
    try:
        snap = read_papergames(page)
    finally:
        dom_reader.UNKNOWN_RETRY_DELAY_S = old
    assert page.calls == 2, f"ожидался повтор, вызовов: {page.calls}"
    assert snap.raw_errors == [] and snap.moves == 1


def test_no_retry_when_clean():
    page = FakePage([dict(BASE_DATA)])
    snap = read_papergames(page)
    assert page.calls == 1 and snap.raw_errors == []


def test_retry_disabled():
    transient = dict(BASE_DATA)
    transient["errors"] = ["unknown disc color null"]
    page = FakePage([transient])
    snap = read_papergames(page, retry_on_unknown=False)
    assert page.calls == 1 and snap.raw_errors


def main():
    test_lock_lifecycle()
    print("  lock: жизненный цикл (acquire / повтор / release) — OK")
    test_lock_stale_cleanup()
    print("  lock: сирота с мёртвым PID удаляется — OK")
    test_ensure_guards()
    print("  lock: ensure_no_bot/ensure_bot (exit 3, --force) — OK")
    test_retry_on_unknown_color()
    print("  reader: retry при 'unknown disc color' — OK")
    test_no_retry_when_clean()
    print("  reader: чистое чтение без повторов — OK")
    test_retry_disabled()
    print("  reader: retry_on_unknown=False — OK")
    print("И1 — ОФЛАЙН-ЧАСТЬ (локфайл + retry): ВСЁ OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
