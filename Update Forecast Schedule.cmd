@echo off
rem Add same-day retry times to the two daily forecast tasks. -ExecutionPolicy Bypass applies to this run only.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-schedule.ps1"
echo.
pause
