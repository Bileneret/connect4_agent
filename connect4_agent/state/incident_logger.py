"""Диагностические дампы при инцидентах — Вопрос №46.

В штатном режиме ничего не пишется. При сбое/рассинхроне/аномалии сохраняется
папка logs/incidents/<метка>-<вид>/ с dump.json (произвольный payload) и, если
передана страница браузера, скриншотом screenshot.png.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE = ROOT / "logs" / "incidents"


def dump_incident(kind: str, payload: dict, page=None, base_dir: Path | None = None) -> Path:
    """Сохранить дамп инцидента и вернуть путь к папке дампа."""
    base = Path(base_dir) if base_dir else DEFAULT_BASE
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = base / f"{stamp}-{kind}"
    folder.mkdir(parents=True, exist_ok=True)

    body = {"kind": kind, "ts": time.time(), "when": time.strftime("%Y-%m-%d %H:%M:%S")}
    body.update(payload)
    (folder / "dump.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    if page is not None:
        try:
            page.screenshot(path=str(folder / "screenshot.png"))
        except Exception:
            pass
    return folder
