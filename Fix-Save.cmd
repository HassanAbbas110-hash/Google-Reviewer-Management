@echo off
cd /d "%~dp0"
echo Close the Review Manager server window before running this fix.
if not exist reviewer\web.py goto wrongfolder
if not exist .venv\Scripts\python.exe goto wrongfolder
.venv\Scripts\python.exe -c "from pathlib import Path; import shutil; p=Path('reviewer/web.py'); s=p.read_text(encoding='utf-8'); old=chr(39)+'Referrer-Policy'+chr(39)+']=' +chr(39)+'no-referrer'+chr(39); new=chr(39)+'Referrer-Policy'+chr(39)+']=' +chr(39)+'same-origin'+chr(39); assert old in s or new in s, 'Unexpected app version. No changes made.'; shutil.copy2(p,p.with_suffix('.py.save-fix-backup')) if not p.with_suffix('.py.save-fix-backup').exists() else None; p.write_text(s.replace(old,new),encoding='utf-8'); print('Save-form fix applied. Business data and settings were not changed.')"
if errorlevel 1 goto failed
echo Start the app with Start.cmd, then press Ctrl+Shift+R in the browser.
pause
exit /b 0
:wrongfolder
echo Put this file in the SAME folder as Start.cmd and Setup.cmd, then run it again.
pause
exit /b 1
:failed
echo Fix was not completed. Please share the error message with your developer.
pause
exit /b 1
