@echo off
if not exist "%~dp0.local\python\python.exe" (
  echo Run Setup.cmd first.
  pause
  exit /b 1
)
"%~dp0.local\python\python.exe" "%~dp0work\campaign_control.py" start
if errorlevel 1 pause
