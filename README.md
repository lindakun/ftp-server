# 局域网文件共享服务器

文件共享服务，提供两种访问方式：

- **网页版（推荐）**：浏览器直接打开，拖拽上传，所见即所得，基于 Python 标准库，**零第三方依赖**
- **FTP 版**：传统 FTP 协议，匿名访问，基于 pyftpdlib

> 注意：Chrome/Edge/Firefox 等现代浏览器已移除 FTP 协议支持，推荐用网页版。

除了文件管理，网页版还带一个 **共享剪切板**，可以在多台设备间传文字和截图。

---

## 快速启动（Windows）

双击 `start.bat`，按菜单选择：

```
 1. HTTP 网页版（推荐，浏览器访问 :8080）
 2. FTP 版（FTP 客户端访问 :21）
 3. 全部启动
```

选 1 后，浏览器打开 `http://<本机IP>:8080` 即可：

```
====================================================
  HTTP 文件共享服务器已启动（网页版）
====================================================
  监听地址   : 0.0.0.0:8080
  共享目录   : <项目目录>\shared
  数据目录   : <项目目录>\data
  上传上限   : 2048 MB
  权限       : 上传 + 下载 + 删除
====================================================
```

`stop.bat` 按端口停止服务器。按 `Ctrl+C` 也可停止。

## 上传文件与文件夹

工具栏三个按钮：

| 按钮 | 作用 |
|------|------|
| 📤 上传文件 | 一次可选多个文件 |
| 📁 上传文件夹 | 选整个文件夹，**目录结构原样保留** |
| 🗂 新建文件夹 | 建空目录 |

**上传目标目录**：按钮下方有一行「上传到 `/xxx`」，默认跟随你当前浏览的目录。
点一下路径就能改成任意目录（比如 `/archive/2026`），不存在会自动创建。
切换目录时上传目标会自动重置为当前目录。

**拖拽**：把文件或**整个文件夹**直接拖进页面即可，目录结构同样保留。

**大文件夹**：会自动分批发送（每批最多 20 个文件或 32MB），进度条显示
「第 N/M 批」和总百分比，不会因为几百个文件卡死。

**限制**：

- **空文件夹不会被上传** —— 浏览器只传文件，不会传文件夹本身，这是协议限制
- 上传时若目标位置已有同名文件会直接覆盖；若被同名**目录**占用，会自动改名为
  `xxx (文件1).ext` 而不是报错
- 单个文件超过 `MAX_UPLOAD_MB`（默认 2048MB）会被跳过并在提示里说明数量

**安全**：上传携带的路径会被清洗，`../`、绝对路径、`C:\` 盘符等一律压平到共享目录内，
不会写到共享目录之外。

## 共享剪切板

网页版第二个 Tab，用来在设备之间传临时内容：

- 发文字：粘贴到文本框点「发布」，其他设备立刻能看到，点「复制」拿走
- 发图片：在剪切板区域直接 `Ctrl+V` 粘贴截图，或拖拽图片进来
- 内容永久保留，最新的在最前面，可单条删除或一键清空
- 存储位置：`data/clipboard.json` + `data/clipboard_files/`（不会污染 `shared/`）

## 局域网内访问

| 客户端 | 用法 |
|--------|------|
| 浏览器（网页版） | 地址栏输入 `http://<服务器IP>:8080` |
| 浏览器（FTP 版） | 地址栏输入 `ftp://<服务器IP>:21` |
| Windows 资源管理器 | 地址栏输入 `ftp://<服务器IP>:21`，可直接拖拽文件 |
| FileZilla 等客户端 | 主机填 IP，端口 21，匿名登录 |
| 命令行 | `ftp <服务器IP>`，用户名 anonymous |

所有上传下载的文件都放在 `shared/` 目录下。

---

## 部署到 Linux 服务器（走 SSH 隧道，不开公网）

适合把服务放到云主机上、只给自己用。**服务只绑 `127.0.0.1`，公网访问不到**，
需要时通过 SSH 隧道连上去。

网页版是纯标准库实现，服务器上**不需要 venv、不需要 pip install**，系统自带
Python 3 即可直接跑。

### 一键部署

在服务器上（Ubuntu 22.04/24.04）：

```bash
sudo bash /opt/fileshare/deploy/install_remote.sh
```

脚本会建好系统用户 `fileshare`、数据目录 `/var/lib/fileshare`、配置
`/etc/fileshare/env`、systemd 单元 `fileshare.service`，并启动服务。重复执行是安全的，
已有配置不会被覆盖。

首次部署时如果 `/opt/fileshare` 还不存在，先把仓库克隆过去再跑脚本：

```bash
sudo install -d -m 0755 -o $USER -g $USER /opt/fileshare
git clone https://github.com/lindakun/ftp-server.git /opt/fileshare
sudo bash /opt/fileshare/deploy/install_remote.sh
```

### 服务器上的布局

| 路径 | 内容 |
|------|------|
| `/opt/fileshare` | 代码（git 仓库，`git pull` 更新） |
| `/var/lib/fileshare/shared` | 用户文件，与代码分离，pull 不会碰到 |
| `/var/lib/fileshare/data` | 剪贴板内容与上传中转 |
| `/etc/fileshare/env` | 运行时配置（端口、目录、上限、时区） |
| `/etc/systemd/system/fileshare.service` | systemd 单元 |

### 日常操作

```bash
sudo systemctl restart fileshare          # 改完配置重启
journalctl -u fileshare -f                # 看日志
sudo systemctl stop fileshare             # 停
sudo systemctl disable --now fileshare    # 卸载（含取消开机自启）
```

### 更新代码

服务端只 `pull`，不要手改服务器上的文件：

```bash
sudo bash /opt/fileshare/deploy/install_remote.sh   # 内部会 git pull 并重启
```

### 本机 SSH 隧道

在 `~/.ssh/config` 的对应主机下加端口转发：

```sshconfig
Host myserver
    HostName <你的服务器IP>
    User <用户名>
    LocalForward 18080 127.0.0.1:18080
    ExitOnForwardFailure yes
```

连接后浏览器打开 `http://127.0.0.1:18080`。也可以临时用：

```bash
ssh -N -L 18080:127.0.0.1:18080 myserver
```

**安全说明**：服务绑 `127.0.0.1`，加上服务器防火墙没放行该端口，公网无法访问。
可以用 `curl <公网IP>:18080` 验证——应当超时。

### systemd 单元里的保护

`fileshare.service` 里带了两道保险，专门针对小内存服务器：

- `MemoryHigh=192M` / `MemoryMax=256M`：服务内存超标就被单独掐掉重启，
  不会连累同机的 sing-box、nginx 等
- `ProtectSystem=strict` + `ReadWritePaths=/var/lib/fileshare` + `NoNewPrivileges=yes`：
  代码目录只读，服务只能写数据目录

---

## 文件说明

```
http_server.py         网页版服务器主程序（推荐）
web/index.html         网页版前端页面（文件 + 共享剪切板两个 Tab）
ftp_server.py          FTP 版服务器主程序
start.bat              统一启动脚本（双击，菜单 1/2/3）
stop.bat               停止服务器（按端口杀进程）
requirements.txt       Python 依赖（仅 FTP 版需要 pyftpdlib）
shared/                共享文件根目录（两种方式共用）
data/                  运行时数据：剪贴板 + 上传中转（不入版本库）
deploy/                Linux 部署文件（service + env.example + 安装脚本）
_test_http.py          网页版自测脚本
_test_ftp.py           FTP 版自测脚本
_test_batch.py         批量下载自测脚本
_test_clipboard.py     共享剪切板自测脚本
install_service.bat    开机自启安装（Windows，双击自动提权）
uninstall_service.bat  开机自启卸载（Windows，双击自动提权）
install_service.py     安装逻辑（被 bat 调用）
uninstall_service.py   卸载逻辑（被 bat 调用）
logs/                  后台运行日志目录（自动生成）
.venv/                 独立 Python 虚拟环境（Windows 上用）
```

## 环境变量

所有配置项都能用环境变量覆盖（Linux 部署靠这个，Windows 直接跑则用默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HTTP_HOST` | `0.0.0.0` | 监听地址。设 `127.0.0.1` 即只允许本机访问 |
| `HTTP_PORT` | `8080` | 监听端口 |
| `SHARE_DIR` | `<脚本目录>/shared` | 共享文件目录 |
| `DATA_DIR` | `<脚本目录>/data` | 剪贴板与上传中转目录 |
| `MAX_UPLOAD_MB` | `2048` | 单文件上传上限，`0` 表示不限制 |
| `CLIPBOARD_MAX_IMAGE_MB` | `20` | 剪切板单张图片上限 |
| `CLIPBOARD_MAX_ENTRIES` | `200` | 剪切板最多保留条数 |
| `TZ` | 系统时区 | 设 `Asia/Shanghai` 让剪切板时间显示正确 |

## 自测

先启动服务器，再另开一个命令行运行：

```bash
# Windows
.venv\Scripts\python.exe _test_http.py
# Linux / macOS（网页版零依赖，用系统 python 即可）
python3 _test_http.py
```

会自动测试连接、上传、下载、删除、建目录、批量打包、剪切板等功能，全部通过即说明运转正常。

## 开机自启（Windows）

双击 `install_service.bat`，弹出 UAC 确认后自动安装：

- 开机自动启动（无需用户登录）
- 后台运行（无窗口，用 `pythonw.exe`）
- 崩溃自动重启（间隔 1 分钟，最多 999 次）
- 日志写入 `logs/server.log`

默认安装网页版。如需同时安装 FTP 版：

```bash
.venv\Scripts\python.exe install_service.py all
```

卸载：双击 `uninstall_service.bat`。

管理命令（管理员 CMD）：

```bash
schtasks /run   /tn FileShareWeb     # 启动
schtasks /end   /tn FileShareWeb     # 停止
schtasks /query /tn FileShareWeb /v  # 查看状态
# FTP 版把 FileShareWeb 换成 FileShareFTP
```

## 修改配置（FTP 版）

编辑 `ftp_server.py` 顶部的「配置区」：

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

**Q: 其他设备连不上（Windows 局域网）？**

检查三件事：

1. 服务器和客户端在同一局域网
2. 服务器窗口没关、IP 地址对得上
3. Windows 防火墙放行 8080 端口；FTP 版还需放行 21 和 60000-60100 端口

**Q: 部署到服务器后，本地浏览器打不开？**

确认三件事：

1. 隧道开着（`ssh -N -L 18080:127.0.0.1:18080 <别名>`，窗口别关）
2. `systemctl is-active fileshare` 是 `active`
3. 服务器上 `curl 127.0.0.1:18080` 有响应

**Q: 能连上但传文件失败？**

- 网页版：看是不是超过了 `MAX_UPLOAD_MB` 上限（默认 2048MB）
- FTP 版：通常是被动模式端口被防火墙挡了，确认 60000-60100 已放行

**Q: 上传大文件失败 / 服务被重启？**

服务设了 `MemoryMax=256M`，超限会被 systemd 掐掉。正常传输是流式落盘的、不占内存，
出现这种情况一般是单文件超过了 `MAX_UPLOAD_MB`，调整 `env` 里的上限即可。

**Q: 中文文件名乱码？**

服务器默认 UTF-8。FTP 老客户端可在设置里把编码改成 UTF-8。

**Q: 上传的音乐如何自动进入 Navidrome 曲库？**

将文件上传到 Navidrome 的 `MusicFolder` 对应目录（或其子目录）。网页版会在发布文件前
将权限设为 `0644`，让 Navidrome 能立即读取；单曲和文件夹上传都适用，中转文件仍为 `0600`。
Navidrome 的目录监视会自动触发扫描，建议同时配置 `Scanner.Schedule = "@every 2m"`
作为兜底。上传完成不等于索引已经完成，扫描结束后即可检索，无需手动修改权限或重启服务。
音频必须是 Navidrome 支持的有效格式；目录本身也需要允许 Navidrome 用户访问。

**Q: 剪切板时间差 8 小时？**

服务器是 UTC 时区。在 `/etc/fileshare/env` 里加 `TZ=Asia/Shanghai` 后重启服务。

**Q: 想要密码访问怎么办？**

网页版目前无鉴权，所以部署方案默认只绑 `127.0.0.1`，靠 SSH 隧道当门禁。
FTP 版可编辑 `ftp_server.py`，在 `authorizer.add_anonymous(...)` 后加：

```python
authorizer.add_user("用户名", "密码", SHARE_DIR, perm="elradfmwMT")
```

## 技术栈

- Python 3（网页版纯标准库；FTP 版依赖 pyftpdlib）
- systemd（Linux 部署）/ Windows 任务计划程序（Windows 自启）
