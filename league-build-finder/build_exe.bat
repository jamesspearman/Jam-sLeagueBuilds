@echo off
rem Builds "Jam's League Builds.exe": one file, no Python needed on the computer that runs it.
cd /d "%~dp0"
title Building Jam's League Builds

set PY=python
where py >nul 2>nul && set PY=py -3

echo Installing the packaging tool (PyInstaller)...
%PY% -m pip install --upgrade --quiet pyinstaller
if errorlevel 1 goto fail

echo Building the .exe (takes about a minute)...
%PY% -m PyInstaller --noconfirm --clean --log-level WARN --onefile --windowed ^
  --name JamsLeagueBuilds --icon icon.ico --version-file version_info.txt ^
  --add-data "static;static" --add-data "icon.ico;." launcher.pyw
if errorlevel 1 goto fail

copy /y "dist\JamsLeagueBuilds.exe" "Jam's League Builds.exe" >nul
if errorlevel 1 goto fail
rmdir /s /q build >nul 2>nul
del /q JamsLeagueBuilds.spec >nul 2>nul

echo.
echo Done: "Jam's League Builds.exe" is in this folder. Send that one file to friends.
pause
exit /b 0

:fail
echo.
echo Build failed. Scroll up for the error and send it to Claude.
pause
exit /b 1
