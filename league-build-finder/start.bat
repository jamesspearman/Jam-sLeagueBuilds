@echo off
cd /d "%~dp0"
title League Build Finder

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app.py %*
) else (
  python app.py %*
)

if errorlevel 1 (
  echo.
  echo Something went wrong. Is Python installed? See README.md.
  pause
)
