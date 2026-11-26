@echo off
rem Connects one business to its Google Business Profile. Close the Review Manager window first.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo Run Setup.cmd first. & pause & exit /b 1 )
if not exist credentials.json (
  echo  credentials.json is missing. Follow docs\GOOGLE_SETUP.md step 3 to download it into this folder.
  pause & exit /b 1
)
set /p BID="Business number (shown on the business page under Google connection): "
.venv\Scripts\python.exe -m reviewer connect %BID% --client credentials.json
pause
