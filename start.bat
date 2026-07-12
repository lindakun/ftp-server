@echo off
chcp 65001>nul
cd /d "%~dp0"

echo ========================================
echo   局域网文件共享服务器
echo ========================================
echo.
echo  1. HTTP 网页版(推荐, 浏览器访问 :8080)
echo  2. FTP 版(FTP 客户端访问 :21)
echo  3. 全部启动
echo.
set /p choice=请选择 (1/2/3):

if "%choice%"=="1" goto web
if "%choice%"=="2" goto ftp
if "%choice%"=="3" goto both
echo 输入无效, 默认启动网页版...
goto web

:web
echo.
echo ========================================
echo   HTTP 文件共享服务器启动中...
echo ========================================
.venv\Scripts\python.exe http_server.py
goto end

:ftp
echo.
echo ========================================
echo   FTP 共享服务器启动中...
echo ========================================
.venv\Scripts\python.exe ftp_server.py
goto end

:both
echo.
echo ========================================
echo   正在启动所有服务...
echo ========================================
start "HTTP网页版 :8080" .venv\Scripts\python.exe http_server.py
start "FTP版 :21" .venv\Scripts\python.exe ftp_server.py
echo 两个服务已分别在新窗口中启动
goto end

:end
echo.
echo 服务器已退出, 按任意键关闭窗口...
pause>nul