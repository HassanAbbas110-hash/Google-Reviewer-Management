@echo off
rem Daily launcher. Opens the Review Manager in your browser. Keep this window open while you work.
cd /d "%~dp0"
title WebRift Review Manager
if not exist .venv\Scripts\python.exe (
  echo First run: setting up. This takes a few minutes once.
  call Setup.cmd
  if not exist .venv\Scripts\python.exe exit /b 1
)
.venv\Scripts\python.exe -m reviewer serve --open-browser
if errorlevel 1 (
  echo.
  echo  The app stopped with a problem ^(message above^). Run Doctor.cmd to check each part.
  pause
)
