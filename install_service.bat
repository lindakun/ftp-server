@echo off
chcp 65001 >nul 2>&1
:: 自动请求管理员权限
>nul 2>&1 net session
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
".venv\Scripts\python.exe" install_service.py
echo.
pause
