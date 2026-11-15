@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo Run Setup.cmd first.
 pause
 exit /b 1
)
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe -m reviewer serve
pause
