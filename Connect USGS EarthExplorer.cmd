@echo off
rem Save a USGS EarthExplorer sign-in (for VegDRI). -ExecutionPolicy Bypass applies to this window only.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0connect-usgs.ps1"
