# 局域网文件共享服务器

局域网内文件共享，提供两种访问方式：
- **网页版（推荐）**：浏览器直接打开，拖拽上传，所见即所得，基于 Python 标准库
- **FTP 版**：传统 FTP 协议，匿名访问，支持上传下载，基于 pyftpdlib

> 注意：Chrome/Edge/Firefox 等现代浏览器已移除 FTP 协议支持，推荐用网页版。

## 快速启动

### 网页版（推荐，浏览器直接访问）

双击 `start_web.bat`，浏览器打开 `http://<本机IP>:8080` 即可。启动后打印：

```
====================================================
  HTTP 文件共享服务器已启动（网页版）
====================================================
  本机 IP    : 192.168.31.193
  访问地址   : http://192.168.31.193:8080
  共享目录   : G:\ftp-server\shared
  权限       : 上传 + 下载 + 删除
====================================================
```

### FTP 版（传统 FTP 客户端用）

双击 `start.bat` 即可。启动后会打印本机 IP 和访问地址，例如：

```
========================================================
  FTP 共享服务器已启动
========================================================
  本机 IP    : 192.168.1.100
  访问地址   : ftp://192.168.1.100:21
  共享目录   : G:\ftp-server\shared
  权限       : 匿名读写（上传 + 下载）
========================================================
```

按 `Ctrl+C` 或直接关闭窗口即可停止服务器。

## 局域网内访问方式

服务器启动后，同一局域网内的设备可以用以下任一方式访问：

| 客户端 | 用法 |
|--------|------|
| 浏览器 | 地址栏输入 `ftp://192.168.1.100:21`（换成实际 IP） |
| Windows 资源管理器 | 地址栏输入 `ftp://192.168.1.100:21`，可直接拖拽文件 |
| FileZilla 等客户端 | 主机填 IP，端口 21，选择匿名登录 |
| 命令行 | `ftp 192.168.1.100`，用户名 anonymous |

所有上传下载的文件都放在 `shared\` 目录下。

## 文件说明

```
http_server.py     网页版服务器主程序（推荐，浏览器访问）
start_web.bat      网页版双击启动脚本
web\index.html     网页版前端页面
ftp_server.py      FTP 版服务器主程序（传统 FTP 客户端用）
start.bat          FTP 版双击启动脚本
requirements.txt   Python 依赖
shared\            共享文件根目录（两种方式共用此目录）
.venv\             独立 Python 虚拟环境
_test_ftp.py       FTP 版自测脚本（可选）
_test_http.py      网页版自测脚本（可选）
_test_batch.py     批量下载自测脚本（可选）
install_service.bat    开机自启安装（双击，自动提权）
uninstall_service.bat  开机自启卸载（双击，自动提权）
install_service.py     安装逻辑（被 bat 调用）
uninstall_service.py   卸载逻辑（被 bat 调用）
logs\              后台运行日志目录（自动生成）
```

## 自测（可选）

想确认服务器是否正常工作，先启动服务器，再另开一个命令行运行：

```bash
# 网页版
.venv\Scripts\python.exe _test_http.py
# FTP 版
.venv\Scripts\python.exe _test_ftp.py
```

会自动测试连接、上传、下载、删除、建目录等功能，全部通过即说明服务器运转正常。

## 开机自启（后台常驻服务）

双击 `install_service.bat`，弹出 UAC 确认后自动安装。安装后服务会：

- **开机自动启动**（无需用户登录）
- **后台运行**（无窗口，用 pythonw.exe）
- **崩溃自动重启**（间隔1分钟，最多999次）
- **日志写入** `logs\server.log`

默认安装网页版。如需同时安装 FTP 版，管理员 CMD 运行：

```bash
.venv\Scripts\python.exe install_service.py all
```

**卸载**：双击 `uninstall_service.bat` 即可取消开机自启。

**管理命令**（管理员 CMD）：

```bash
schtasks /run   /tn FileShareWeb     # 启动网页版
schtasks /end   /tn FileShareWeb     # 停止网页版
schtasks /query /tn FileShareWeb /v  # 查看状态
# FTP 版把 FileShareWeb 换成 FileShareFTP
```

**查看后台日志**：打开 `logs\server.log`

## 修改配置

编辑 `ftp_server.py` 顶部的「配置区」即可调整：

- `PORT`：端口号，默认 21，被占用可改成 2121 等
- `ANON_PERM`：权限字符串，去掉某些字母即限制操作（如去掉 `w` 禁止上传）
- `MAX_CONS` / `MAX_CONS_PER_IP`：并发连接限制
- `PASV_PORT_START` / `PASV_PORT_END`：被动模式端口范围

权限字母含义：

| 字母 | 含义 | 字母 | 含义 |
|------|------|------|------|
| e | 切换目录 | m | 创建目录 |
| l | 列出文件 | w | 上传文件 |
| r | 读取/下载 | d | 删除文件 |
| a | 追加上传 | f | 重命名 |
| M | 修改权限 | T | 修改时间 |

## 常见问题

**Q: 其他设备连不上？**
检查三件事：
1. 服务器和客户端在同一局域网
2. 服务器窗口没关、IP 地址对得上
3. Windows 防火墙放行 21 端口和 60000-60100 端口（本机专用/公用网络防火墙已关闭则无需处理）

**Q: 能连上但传文件失败/卡住？**
通常是被动模式端口被防火墙挡了。确认 60000-60100 端口未被占用且放行。

**Q: 中文文件名乱码？**
服务器已默认 UTF-8 编码。若客户端是老版本，可在客户端设置里把编码改成 UTF-8。

**Q: 想要密码访问怎么办？**
编辑 `ftp_server.py`，在 `authorizer.add_anonymous(...)` 后面加一行：
```python
authorizer.add_user("用户名", "密码", SHARE_DIR, perm="elradfmwMT")
```

## 技术栈

- Python 3.13
- pyftpdlib（最成熟的纯 Python FTP 服务器库）
