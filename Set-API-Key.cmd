@echo off
rem Stores an Anthropic API key in Windows Credential Manager so drafts use the Claude API.
rem Get a key at https://console.anthropic.com (Settings, API keys). Close the Review Manager first.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo Run Setup.cmd first. & pause & exit /b 1 )
if /i "%~1"=="remove" ( .venv\Scripts\python.exe -m reviewer apikey --remove ) else ( .venv\Scripts\python.exe -m reviewer apikey )
pause
