@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "..\.venv\Scripts\python.exe" (
    echo [start_bot] Создаю виртуальное окружение...
    py -3 -m venv ..\.venv
    echo [start_bot] Устанавливаю зависимости...
    ..\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
)

..\.venv\Scripts\python.exe run.py %*
