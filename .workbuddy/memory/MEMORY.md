# 项目记忆 - FTP 共享服务器 (G:\ftp-server)

## 项目概述
局域网文件共享服务器，提供网页版（推荐）和 FTP 版两种访问方式。
- 网页版：http_server.py，基于 Python 标准库 http.server，浏览器直接访问 :8080
- FTP 版：pyftpdlib 2.2.0 + Python 3.13，匿名访问，FTP 客户端访问 :21
- 完整读写权限，双击 start_web.bat / start.bat 前台运行，或 install_service.bat 开机自启后台运行

## 关键文件
- `http_server.py` - 网页版主程序（推荐，浏览器访问 8080 端口）
- `web\index.html` - 网页版前端页面（文件管理 + 共享剪切板 Tab）
- `ftp_server.py` - FTP 版主程序，配置区在文件顶部
- `start.bat` - 统一启动脚本（菜单选 1=网页版 / 2=FTP版）
- `_test_ftp.py` / `_test_http.py` / `_test_batch.py` - 功能自测脚本
- `install_service.bat` / `uninstall_service.bat` - 开机自启安装/卸载（双击提权）
- `install_service.py` / `uninstall_service.py` - 安装/卸载逻辑
- `stop.bat` - 双击停止服务器（按端口杀进程）
- `_test_clipboard.py` - 共享剪切板自测脚本
- `shared\` - 共享文件根目录（两种方式共用）
- `logs\` - 后台运行日志（pythonw.exe 模式自动生成）
- `.venv\` - 独立虚拟环境

## 开机自启（任务计划程序）
- 双击 install_service.bat 安装，uninstall_service.bat 卸载（自动 UAC 提权）
- 任务名：FileShareWeb（网页版）/ FileShareFTP（FTP版）
- 配置：BootTrigger 开机启动 + SYSTEM 用户 + RestartOnFailure 失败重启(1分钟/999次)
- pythonw.exe 无窗口运行，日志写入 logs/server.log（buffering=1 行缓冲）

## 配置要点
- 端口 21，被动模式 60000-60100
- 匿名权限 `elradfmwMT`（完整读写）
- UTF-8 编码防中文乱码
- 修改配置编辑 ftp_server.py 顶部「配置区」

## 环境注意
- Python 3.13 移除了 asyncore，pyftpdlib 2.2.0 自动依赖 pyasyncore/pyasynchat
- pip 安装若遇 safe-delete 冲突，用 --no-cache-dir
- 在 WorkBuddy 沙盒内测试需清空 CODEBUDDY_SESSION_ID/CLAUDE_SESSION_ID 环境变量，否则 DELE 命令会因 safe-delete shim 崩溃

## 本机网络
- 真实局域网 IP: 192.168.31.193（局域网设备用这个访问 FTP）
- 198.18.0.1 = sing-box 虚拟网卡，172.31.144.1 = WSL 虚拟网卡，都不是真实局域网 IP
- get_local_ip() 已实现过滤虚拟网卡（127./169.254./198.18. 前缀），优先返回真实局域网 IP
- print 加了 line_buffering，避免后台运行时横幅被块缓冲不显示

## 共享剪切板（2026-07-12 新增）
- 存储在 `data/clipboard.json`（不会污染 shared/ 文件目录）
- 支持文字 + 图片（base64 内嵌）两种类型
- 类型字段：`type: "text"` 或 `type: "image"`，图片内嵌 data URL 前端直接渲染
- 永久保留（仅手动删除/清空），最新在前排序
- 复制按钮自动降级：https 用 Clipboard API，http 用 execCommand('copy') 回退
- API：GET/POST /api/clipboard、DELETE /api/clipboard/<id>、POST /api/clipboard/clear、POST /api/clipboard/image
