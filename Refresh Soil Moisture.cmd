@echo off
rem Assemble recent NASA soil-moisture inputs and issue the root-zone forecast.
rem -ExecutionPolicy Bypass applies to this run only; system settings are unchanged.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0root-zone-update.ps1" %*
echo.
pause
