@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [start_server] No virtual environment found at .venv
    echo [start_server] Run this once to set it up:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -e ".[server]"
    goto :fail
)

if not exist "%~dp0.env" (
    echo [start_server] .env not found, copying .env.example to .env
    copy /y "%~dp0.env.example" "%~dp0.env" >nul
    echo [start_server] Edit .env and fill in your DNSE API key/secret, then run again.
    goto :fail
)

echo [start_server] Starting DNSE OpenAPI local server...
echo [start_server] Docs: http://127.0.0.1:8000/docs
echo [start_server] Press Ctrl+C to stop.
echo.

"%VENV_PY%" -m dnse_openapi.server
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [start_server] Server exited with code %EXIT_CODE%.
    goto :fail
)

goto :eof

:fail
echo.
pause
exit /b 1
