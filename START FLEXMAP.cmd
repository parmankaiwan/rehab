@echo off
setlocal
cd /d "%~dp0"
title FlexMap Application
set "FLEXMAP_PYTHON=%~dp0..\CV part\.venv\Scripts\python.exe"
if not exist "%FLEXMAP_PYTHON%" (
  echo FlexMap Python environment was not found:
  echo %FLEXMAP_PYTHON%
  pause
  exit /b 1
)
"%FLEXMAP_PYTHON%" flexmap_lifecycle.py start
if errorlevel 1 (
  echo.
  echo FlexMap could not start. Review data\runtime\logs for details.
  pause
)
endlocal
