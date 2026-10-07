@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Yukiyasha — launcher

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "HOST=127.0.0.1"
set "DEFAULT_PORT=8000"
set "PORT=%YUKIYASHA_PORT%"
if not defined PORT set "PORT=%DEFAULT_PORT%"
set "MAX_PORT=8010"

cls
echo.
echo ╔══════════════════════════════════════════════╗
echo ║                 Y U K I Y A S H A            ║
echo ║            локальный веб-лаунчер             ║
echo ╚══════════════════════════════════════════════╝
echo.

call :check_python
if errorlevel 1 goto :fatal

call :ensure_venv
if errorlevel 1 goto :fatal

call :check_venv_python
if errorlevel 1 goto :fatal

call :ensure_dependencies
if errorlevel 1 goto :fatal

call :select_port
if errorlevel 1 goto :fatal

set "APP_URL=http://%HOST%:%PORT%"
set "HEALTH_URL=%APP_URL%/api/health"

echo.
echo [Yukiyasha] Среда готова.
echo [Yukiyasha] Адрес: %APP_URL%
echo [Yukiyasha] Порт:   %PORT%
echo.
echo Для остановки нажмите Ctrl+C или закройте это окно.
echo.

rem Браузер откроется только после появления health endpoint.
start "" powershell -NoProfile -WindowStyle Hidden -Command ^
  "$url='%APP_URL%'; $health='%HEALTH_URL%';" ^
  "for($i=0;$i -lt 30;$i++){" ^
  "  try{ $r=Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 1; if($r.StatusCode -eq 200){Start-Process $url; exit 0} }catch{};" ^
  "  Start-Sleep -Milliseconds 500" ^
  "}; exit 1"

"%PYTHON_EXE%" -m uvicorn yukiyasha.web.app:app --host %HOST% --port %PORT%

set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
    echo [Yukiyasha] Сервер остановлен.
) else (
    echo [ОШИБКА] Сервер завершился с кодом %EXIT_CODE%.
    echo Проверьте сообщение выше.
    pause
)
exit /b %EXIT_CODE%

:check_python
echo [1/5] Проверка Python...
where py >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%V in ('py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "SYSTEM_PY_VERSION=%%V"
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY_LAUNCHER=py -3"
        echo [OK] Python !SYSTEM_PY_VERSION!
        exit /b 0
    )
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден.
    echo Требуется Python 3.11 или новее.
    echo Скачать: https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=*" %%V in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "SYSTEM_PY_VERSION=%%V"
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Найден Python !SYSTEM_PY_VERSION!, но нужен Python 3.11 или новее.
    exit /b 1
)

set "PY_LAUNCHER=python"
echo [OK] Python !SYSTEM_PY_VERSION!
exit /b 0

:ensure_venv
echo [2/5] Проверка виртуальной среды...
if exist "%PYTHON_EXE%" (
    echo [OK] .venv найден.
    exit /b 0
)

echo [Yukiyasha] Создаю локальную среду .venv...
%PY_LAUNCHER% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось создать .venv.
    exit /b 1
)
echo [OK] .venv создан.
exit /b 0

:check_venv_python
echo [3/5] Проверка Python внутри .venv...
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] .venv повреждён или создан неподдерживаемой версией Python.
    echo Удалите папку .venv и запустите Yukiyasha.bat снова.
    exit /b 1
)
echo [OK] Виртуальная среда исправна.
exit /b 0

:ensure_dependencies
echo [4/5] Проверка зависимостей...
"%PYTHON_EXE%" -c "import fastapi, uvicorn, yukiyasha" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Зависимости установлены.
    exit /b 0
)

echo [Yukiyasha] Устанавливаю зависимости проекта...
"%PYTHON_EXE%" -m pip install -e .
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    echo Проверьте подключение к интернету и доступ к PyPI.
    exit /b 1
)

"%PYTHON_EXE%" -c "import fastapi, uvicorn, yukiyasha" >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Установка завершилась, но импорт зависимостей не проходит.
    exit /b 1
)

echo [OK] Зависимости готовы.
exit /b 0

:select_port
echo [5/5] Проверка порта...

set /a CURRENT_PORT=%PORT%
if !CURRENT_PORT! LSS 1 (
    echo [ОШИБКА] Некорректный порт: %PORT%
    exit /b 1
)
if !CURRENT_PORT! GTR 65535 (
    echo [ОШИБКА] Некорректный порт: %PORT%
    exit /b 1
)

:port_loop
call :is_port_busy !CURRENT_PORT!
if errorlevel 1 (
    set "PORT=!CURRENT_PORT!"
    echo [OK] Порт !PORT! свободен.
    exit /b 0
)

call :is_yukiyasha !CURRENT_PORT!
if not errorlevel 1 (
    set "PORT=!CURRENT_PORT!"
    set "APP_URL=http://%HOST%:!PORT!"
    echo [Yukiyasha] Уже запущена на !APP_URL!
    start "" "!APP_URL!"
    exit /b 2
)

echo [Yukiyasha] Порт !CURRENT_PORT! занят другим процессом.

if defined YUKIYASHA_PORT (
    echo [ОШИБКА] Порт задан через YUKIYASHA_PORT и недоступен.
    exit /b 1
)

set /a CURRENT_PORT+=1
if !CURRENT_PORT! GTR %MAX_PORT% (
    echo [ОШИБКА] Нет свободного порта в диапазоне %DEFAULT_PORT%-%MAX_PORT%.
    echo Освободите один из портов или задайте YUKIYASHA_PORT вручную.
    exit /b 1
)
goto :port_loop

:is_port_busy
set "CHECK_PORT=%~1"
powershell -NoProfile -Command ^
  "$p=%CHECK_PORT%; $busy=$false;" ^
  "try{$busy=[bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop)}catch{" ^
  "  $busy=[bool](netstat -ano -p tcp ^| Select-String (':'+$p+'\s+.*LISTENING'))" ^
  "}; if($busy){exit 0}else{exit 1}" >nul 2>&1
exit /b %ERRORLEVEL%

:is_yukiyasha
set "CHECK_PORT=%~1"
powershell -NoProfile -Command ^
  "try{" ^
  "  $r=Invoke-RestMethod -Uri 'http://%HOST%:%CHECK_PORT%/api/health' -TimeoutSec 1;" ^
  "  if($r.service -eq 'Yukiyasha'){exit 0}else{exit 1}" ^
  "}catch{exit 1}" >nul 2>&1
exit /b %ERRORLEVEL%

:fatal
echo.
echo Запуск Yukiyasha остановлен из-за ошибки.
echo.
pause
exit /b 1
