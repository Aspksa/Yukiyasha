@echo off
setlocal EnableExtensions DisableDelayedExpansion
for /f "tokens=2 delims=:" %%C in ('chcp') do set "ORIGINAL_CODEPAGE=%%C"
chcp 65001 >nul
title Yukiyasha — launcher

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "DEPS_MARKER=%VENV_DIR%\.yukiyasha-deps.sha256"
set "HOST=127.0.0.1"
set "DEFAULT_PORT=8000"
set "MAX_PORT=8010"
set "CHECK_ONLY=0"
set "FIXED_PORT=0"
set "ALREADY_RUNNING=0"
set "INSTALL_ATTEMPTED=0"

set "PORT=%YUKIYASHA_PORT%"
if defined PORT set "FIXED_PORT=1"
if not defined PORT set "PORT=%DEFAULT_PORT%"

if /I "%~1"=="--check" (
    set "CHECK_ONLY=1"
) else if not "%~1"=="" (
    set "PORT=%~1"
    set "FIXED_PORT=1"
)

cls
echo.
echo ╔══════════════════════════════════════════════╗
echo ║                 Y U K I Y A S H A            ║
echo ║            локальный веб-лаунчер             ║
echo ╚══════════════════════════════════════════════╝
echo.

call :validate_port
if errorlevel 1 goto :fatal

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

if "%CHECK_ONLY%"=="1" (
    echo.
    echo [OK] Диагностика завершена успешно.
    if "%ALREADY_RUNNING%"=="1" (
        echo [OK] Yukiyasha уже работает на http://%HOST%:%PORT%
    ) else (
        echo [OK] Для запуска доступен порт %PORT%.
    )
    call :restore_console
    exit /b 0
)

set "APP_URL=http://%HOST%:%PORT%"
set "HEALTH_URL=%APP_URL%/api/health"

if "%ALREADY_RUNNING%"=="1" (
    echo.
    echo [Yukiyasha] Уже запущена: %APP_URL%
    if /I not "%YUKIYASHA_NO_BROWSER%"=="1" start "" "%APP_URL%"
    call :restore_console
    exit /b 0
)

echo.
echo [Yukiyasha] Среда готова.
echo [Yukiyasha] Адрес: %APP_URL%
echo [Yukiyasha] Порт:   %PORT%
echo.
echo Для остановки нажмите Ctrl+C или закройте это окно.
echo.

if /I not "%YUKIYASHA_NO_BROWSER%"=="1" (
    start "" powershell -NoProfile -WindowStyle Hidden -Command ^
      "$url='%APP_URL%'; $health='%HEALTH_URL%';" ^
      "for($i=0;$i -lt 30;$i++){" ^
      "  try{ $r=Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 1; if($r.StatusCode -eq 200){Start-Process $url; exit 0} }catch{};" ^
      "  Start-Sleep -Milliseconds 500" ^
      "}; exit 1"
)

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
call :restore_console
exit /b %EXIT_CODE%

:check_python
echo [1/5] Проверка Python...
where py >nul 2>&1
if errorlevel 1 goto :try_python
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 goto :try_python
for /f "tokens=*" %%V in ('py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "SYSTEM_PY_VERSION=%%V"
set "PY_LAUNCHER=py -3"
echo [OK] Python %SYSTEM_PY_VERSION%
exit /b 0

:try_python
where python >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден.
    echo Требуется Python 3.11 или новее.
    echo Скачать: https://www.python.org/downloads/
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Нужен Python 3.11 или новее.
    exit /b 1
)
for /f "tokens=*" %%V in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set "SYSTEM_PY_VERSION=%%V"
set "PY_LAUNCHER=python"
echo [OK] Python %SYSTEM_PY_VERSION%
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
for /f "delims=" %%H in ('%PYTHON_EXE% -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('pyproject.toml').read_bytes()).hexdigest())"') do set "CURRENT_DEPS_HASH=%%H"
if not defined CURRENT_DEPS_HASH (
    echo [ОШИБКА] Не удалось вычислить контрольную сумму pyproject.toml.
    exit /b 1
)

if /I "%YUKIYASHA_SKIP_INSTALL%"=="1" goto :verify_dependencies

set "SAVED_DEPS_HASH="
if exist "%DEPS_MARKER%" set /p SAVED_DEPS_HASH=<"%DEPS_MARKER%"
if /I "%SAVED_DEPS_HASH%"=="%CURRENT_DEPS_HASH%" goto :verify_dependencies

:install_dependencies
if "%INSTALL_ATTEMPTED%"=="1" (
    echo [ОШИБКА] Зависимости не проходят проверку после установки.
    echo Удалите папку .venv и запустите Yukiyasha.bat снова.
    exit /b 1
)
set "INSTALL_ATTEMPTED=1"
echo [Yukiyasha] Конфигурация зависимостей изменилась. Обновляю среду...
"%PYTHON_EXE%" -m pip install -e .
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    echo Проверьте подключение к интернету и доступ к PyPI.
    exit /b 1
)
>"%DEPS_MARKER%" echo %CURRENT_DEPS_HASH%

:verify_dependencies
"%PYTHON_EXE%" -c "import fastapi, uvicorn, yukiyasha; from importlib.metadata import version; version('yukiyasha')" >nul 2>&1
if errorlevel 1 (
    if /I "%YUKIYASHA_SKIP_INSTALL%"=="1" (
        echo [ОШИБКА] Предустановленные зависимости неполны.
        exit /b 1
    )
    goto :install_dependencies
)

if not exist "%DEPS_MARKER%" >"%DEPS_MARKER%" echo %CURRENT_DEPS_HASH%
echo [OK] Зависимости соответствуют pyproject.toml.
exit /b 0

:validate_port
set "PORT_CANDIDATE=%PORT%"
powershell -NoProfile -Command ^
  "$v=$env:PORT_CANDIDATE; $p=0;" ^
  "if([int]::TryParse($v,[ref]$p) -and $p -ge 1 -and $p -le 65535 -and $v -ceq $p.ToString()){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Некорректный порт: "%PORT%"
    exit /b 1
)
exit /b 0

:select_port
echo [5/5] Проверка порта...
set /a CURRENT_PORT=%PORT%

:port_loop
call :is_port_busy %CURRENT_PORT%
set "PORT_CHECK_RC=%ERRORLEVEL%"
if %PORT_CHECK_RC% GEQ 2 (
    echo [ОШИБКА] Не удалось проверить состояние порта %CURRENT_PORT%.
    exit /b 1
)
if "%PORT_CHECK_RC%"=="1" (
    set "PORT=%CURRENT_PORT%"
    echo [OK] Порт %CURRENT_PORT% свободен.
    exit /b 0
)

call :is_yukiyasha %CURRENT_PORT%
if not errorlevel 1 (
    set "PORT=%CURRENT_PORT%"
    set "ALREADY_RUNNING=1"
    echo [OK] Найден уже запущенный Yukiyasha на порту %CURRENT_PORT%.
    exit /b 0
)

echo [Yukiyasha] Порт %CURRENT_PORT% занят другим процессом.
if "%FIXED_PORT%"=="1" (
    echo [ОШИБКА] Выбранный фиксированный порт недоступен.
    exit /b 1
)

set /a CURRENT_PORT+=1
if %CURRENT_PORT% GTR %MAX_PORT% (
    echo [ОШИБКА] Нет свободного порта в диапазоне %DEFAULT_PORT%-%MAX_PORT%.
    echo Освободите один из портов или задайте порт вручную:
    echo   Yukiyasha.bat 8090
    exit /b 1
)
goto :port_loop

:is_port_busy
set "CHECK_PORT=%~1"
powershell -NoProfile -Command ^
  "$p=%CHECK_PORT%;" ^
  "try {" ^
  "  try {" ^
  "    $listeners=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop;" ^
  "    if($listeners){exit 0}else{exit 1}" ^
  "  } catch {" ^
  "    $lines=& netstat -ano -p tcp 2>$null;" ^
  "    if($LASTEXITCODE -ne 0){exit 2};" ^
  "    if($lines -match (':'+$p+'\s+.*LISTENING')){exit 0}else{exit 1}" ^
  "  }" ^
  "} catch { exit 2 }" >nul 2>&1
exit /b %ERRORLEVEL%

:is_yukiyasha
set "CHECK_PORT=%~1"
powershell -NoProfile -Command ^
  "try{" ^
  "  $r=Invoke-RestMethod -Uri 'http://%HOST%:%CHECK_PORT%/api/health' -TimeoutSec 1;" ^
  "  if($r.service -eq 'Yukiyasha'){exit 0}else{exit 1}" ^
  "}catch{exit 1}" >nul 2>&1
exit /b %ERRORLEVEL%

:restore_console
if defined ORIGINAL_CODEPAGE chcp %ORIGINAL_CODEPAGE% >nul 2>&1
exit /b 0

:fatal
echo.
echo Запуск Yukiyasha остановлен из-за ошибки.
echo.
call :restore_console
if "%CHECK_ONLY%"=="1" exit /b 1
pause
exit /b 1
