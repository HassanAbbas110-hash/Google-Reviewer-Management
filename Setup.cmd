@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto failed
echo Setup complete. Run Start.cmd to open the application.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.11 or newer from python.org and retry.
pause
exit /b 1
