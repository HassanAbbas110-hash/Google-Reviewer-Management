@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto wrongfolder
if not exist quality-update\install.py goto wrongfolder
echo Close the Review Manager terminal window before continuing.
.venv\Scripts\python.exe quality-update\install.py
if errorlevel 1 goto failed
pause
exit /b 0
:wrongfolder
echo Copy BOTH Update-Reply-Quality.cmd and the quality-update folder beside Start.cmd.
pause
exit /b 1
:failed
echo Update did not complete. Read the message above and share it if you need help.
pause
exit /b 1
