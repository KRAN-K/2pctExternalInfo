@echo off
rem Double-click launcher for SD Card Checker. Starts the app (it asks for administrator rights itself).
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0SDCardChecker.py"
    exit /b
)
where pyw >nul 2>&1
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0SDCardChecker.py"
    exit /b
)
echo Python was not found. Installing Python 3.12 with winget...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if %errorlevel% NEQ 0 (
    echo.
    echo Automatic install failed. Install Python from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH", then double-click this file again.
    pause
    exit /b 1
)
echo.
echo Python installed. Close this window and double-click SDCardChecker.bat again.
pause
