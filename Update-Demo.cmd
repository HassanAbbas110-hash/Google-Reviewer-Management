@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto wrongfolder
if not exist demo-update\install.py goto wrongfolder
echo Close the Review Manager terminal window before continuing.
.venv\Scripts\python.exe demo-update\install.py
if errorlevel 1 goto failed
pause
exit /b 0
:wrongfolder
echo Copy BOTH Update-Demo.cmd and the demo-update folder beside Start.cmd, then try again.
pause
exit /b 1
:failed
echo Update did not complete. Read the message above and share it if you need help.
pause
exit /b 1
