"""Пути для запуска pytest из любого каталога (README: «pytest connect4_agent/tests»).

Файлы тестов исторически запускались напрямую (`python tests/test_x.py`) — тогда
каталог скрипта попадает в sys.path и `import _cdp_testutil` находит модуль-помощник.
При запуске через pytest этого не происходит, поэтому пути добавляются здесь:
каталог tests (для _cdp_testutil) и корень пакета (для browser/, engine/, config).
"""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = TESTS_DIR.parent

for path in (str(TESTS_DIR), str(PACKAGE_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)
