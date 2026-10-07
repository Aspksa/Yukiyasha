@echo off
setlocal EnableExtensions
title Yukiyasha

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "APP_URL=http://127.0.0.1:8000"

echo.
echo ==========================================
echo              Y U K I Y A S H A
echo ==========================================
echo.

if not exist "%PYTHON_EXE%" (
    echo [Yukiyasha] Python environment not found. Creating .venv...

    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%VENV_DIR%"
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            echo [ERROR] Python 3.11 or newer was not found.
            echo Install Python from https://www.python.org/downloads/
            echo and enable "Add Python to PATH".
            echo.
            pause
            exit /b 1
        )
        python -m venv "%VENV_DIR%"
    )

    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo [Yukiyasha] Checking dependencies...
"%PYTHON_EXE%" -c "import fastapi, uvicorn, yukiyasha" >nul 2>&1
if errorlevel 1 (
    echo [Yukiyasha] Installing project dependencies...
    "%PYTHON_EXE%" -m pip install --upgrade pip
    if errorlevel 1 goto :install_error

    "%PYTHON_EXE%" -m pip install -e .
    if errorlevel 1 goto :install_error
)

echo [Yukiyasha] Starting web interface...
echo [Yukiyasha] %APP_URL%
echo.
echo Close this window or press Ctrl+C to stop Yukiyasha.
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"

"%PYTHON_EXE%" -m uvicorn yukiyasha.web.app:app --host 127.0.0.1 --port 8000

if errorlevel 1 (
    echo.
    echo [ERROR] Yukiyasha stopped with an error.
    pause
    exit /b 1
)

exit /b 0

:install_error
echo.
echo [ERROR] Could not install Yukiyasha dependencies.
echo Check your internet connection and Python installation.
pause
exit /b 1
