@echo off
rem Get the newest version. Your businesses, reviews and settings in the data folder are kept.
cd /d "%~dp0"
title WebRift Review Manager - update
echo  Close the Review Manager window first ^(the one Start.cmd opened^).
pause
if exist data\reviews.db (
  if not exist data\backups mkdir data\backups
  copy /y data\reviews.db "data\backups\before-update-%date:~-4%%date:~3,2%%date:~0,2%-%random%.db" >nul
  echo  Backed up data\reviews.db to data\backups\
)
if exist .git (
  git pull --ff-only
  if errorlevel 1 ( echo  Could not download the update. Fix: open GitHub Desktop, click "Fetch origin" then "Pull origin". & pause & exit /b 1 )
) else (
  echo  This folder is not a Git copy. Download the new ZIP, extract it, and copy your old "data" folder into it.
)
call Setup.cmd
