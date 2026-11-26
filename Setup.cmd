@echo off
rem One-time setup. Safe to run again (it also repairs a broken install).
cd /d "%~dp0"
title WebRift Review Manager - setup
echo.
echo  [1/4] Checking Python...
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo  Python 3.11 or newer is missing.
  echo  Fix: install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run Setup.cmd again.
  pause & exit /b 1
)
echo  [2/4] Creating the app environment...
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 ( echo  Could not create .venv. Fix: delete the .venv folder and run Setup.cmd again. & pause & exit /b 1 )
echo  [3/4] Installing components (needs internet)...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 ( echo  Install failed. Fix: check the internet connection and run Setup.cmd again. & pause & exit /b 1 )
echo  [4/4] Self-test...
.venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py" >setup-test.log 2>&1
if errorlevel 1 ( echo  Self-test failed. Details are in setup-test.log. Send that file to your developer. & pause & exit /b 1 )
del setup-test.log >nul 2>&1
echo.
echo  AI drafts: double-click Set-API-Key.cmd and paste an Anthropic API key ^(recommended: fast, best replies^).
echo  No key? The free local option is Ollama: https://ollama.com/download then  ollama pull qwen3:4b
echo.
echo  Setup complete. Double-click Start.cmd to open the Review Manager.
pause
