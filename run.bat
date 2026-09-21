@echo off
chcp 65001 >nul
pushd "%~dp0"
if not exist .venv (
    echo Первый запуск: устанавливаю зависимости...
    py -3 -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe main.py
