@echo off
chcp 65001 >nul 2>&1
title Stop File Share Server
echo ========================================
echo   Stop FTP / Web File Share Server
echo ========================================
echo.

set FOUND=0

REM --- Stop Web version (port 8080) ---
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8080 " ^| findstr "LISTENING"') do (
    echo Killing web server PID %%a on port 8080
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)

REM --- Stop FTP version (port 21) ---
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":21 " ^| findstr "LISTENING"') do (
    echo Killing FTP server PID %%a on port 21
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)

echo.
if "%FOUND%"=="0" (
    echo No running server process found.
) else (
    echo Server stopped.
)
echo.
pause
