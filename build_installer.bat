@echo off
chcp 65001 >nul
rem Полная сборка установщика Windows: PyInstaller -> Inno Setup.
rem Результат: installer\Output\AnimeApp-Setup-<версия>.exe
pushd "%~dp0"
call "%~dp0build.bat" || exit /b 1
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
    echo Не найден Inno Setup 6. Установите: winget install JRSoftware.InnoSetup
    exit /b 1
)
"%ISCC%" installer\AnimeApp.iss
