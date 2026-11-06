@echo off
rem Rebuild the farmer web pages from the newest forecasts, then open them in the default browser.
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\build_app.py" >nul
if errorlevel 1 (
  echo The app pages could not be rebuilt. Opening the last built version.
  pause
)
start "" "%~dp0app\index.html"
