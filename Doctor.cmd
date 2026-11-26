@echo off
rem Checks every part (database, AI model, Google, alerts) and says how to fix problems.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo Run Setup.cmd first. & pause & exit /b 1 )
.venv\Scripts\python.exe -m reviewer doctor
pause
