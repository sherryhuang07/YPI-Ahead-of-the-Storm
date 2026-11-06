@echo off
rem Issue today's sealed 14-day test forecasts for every isolated model and score earlier ones.
rem -ExecutionPolicy Bypass applies to this run only; system settings are unchanged.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0daily-forecasts.ps1"
echo.
if "%~1"=="" pause
