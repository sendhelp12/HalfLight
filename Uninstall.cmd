@echo off
if not exist "%~dp0.local\python\python.exe" (
  echo No installer runtime found. No game files were changed.
  pause
  exit /b 1
)
"%~dp0.local\python\python.exe" "%~dp0work\install_files.py" --uninstall
pause
