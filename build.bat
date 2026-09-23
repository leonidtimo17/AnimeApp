@echo off
chcp 65001 >nul
rem Сборка отдельного AnimeApp.exe (папка dist\AnimeApp), Python для запуска не нужен.
pushd "%~dp0"
.venv\Scripts\python -m pip install -q pyinstaller
.venv\Scripts\pyinstaller --noconfirm --windowed --name AnimeApp ^
  --icon "anime_app\assets\icon.ico" ^
  --collect-submodules webview --hidden-import clr ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.QtQuick3D --exclude-module PySide6.QtCharts ^
  --exclude-module PySide6.QtDataVisualization --exclude-module PySide6.QtPdf --exclude-module PIL ^
  --add-data "anime_app\assets;anime_app\assets" ^
  --add-data "TERMS.md;." --add-data "PRIVACY.md;." ^
  --add-data "LICENSE;." --add-data "THIRD_PARTY_NOTICES.md;." ^
  main.py
echo.
echo Готово: dist\AnimeApp\AnimeApp.exe
