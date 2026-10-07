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
  上传上限   : 4096 MB
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

**大文件上传**：单文件默认上限 4GiB，支持 16 个约 2.5GB 文件依次上传。超过 32MB 的文件独立发送，不会拆分成文件切片。单文件遇到网络中断、连接读取超时或服务繁忙时，最多自动重新上传两次；不支持断点续传，重试会从头发送。上传总时长没有固定限制，连续 10 分钟收不到数据才会超时。

服务端以 64KB 分块落盘，同时最多处理两个文件上传请求；同一网页只运行一组上传任务。上传前检查中转盘和目标盘的空间，并保留至少 64MB 余量。上传中断、数据不完整或写入失败不会发布当前残缺文件，会清理中转文件。多文件批次中已经完整发布的文件会保留。

Windows 上传约 40GB 新文件，建议使用 NTFS/exFAT，保留至少 50GB 可用空间，中转目录 `DATA_DIR` 与共享目录 `SHARE_DIR` 尽量同盘。传输期间保持电脑唤醒；实际速度取决于网络和磁盘。空间预检查不能阻止其他程序或并发上传占满磁盘，仍需预留余量。

**限制**：

- **空文件夹不会被上传** —— 浏览器只传文件，不会传文件夹本身，这是协议限制
- 上传时若目标位置已有同名文件会直接覆盖；若被同名**目录**占用，会自动改名为
  `xxx (文件1).ext` 而不是报错
- 单个文件超过 `MAX_UPLOAD_MB`（默认 4096MB）会被跳过并在提示里说明数量

**安全**：上传携带的路径会被清洗，`../`、绝对路径、`C:\` 盘符等一律压平到共享目录内，
不会写到共享目录之外。

## 共享剪切板

网页版第二个 Tab，用来在设备之间传临时内容：

- 发文字：粘贴到文本框点「发布」，其他设备立刻能看到，点「复制」拿走
- 发图片：在剪切板区域直接 `Ctrl+V` 粘贴截图，或拖拽图片进来
- **搜索**：右上角搜索框即时过滤共享内容，按文字内容匹配（大小写不敏感），命中的关键词高亮
- **编辑**：点「✏️ 编辑」就地修改已发布的文字，`Ctrl+Enter` 保存、`Esc` 取消，保存后带「已编辑」标记（图片不支持编辑，删了重发即可）
- 内容永久保留，最新的在最前面，可单条删除或一键清空
- 存储位置：`data/clipboard.json` + `data/clipboard_files/`（不会污染 `shared/`）

## 局域网内访问

### 剪切板双活（188 NAS + 193 Windows）

两台各自保存完整的剪切板文字和图片，都可以独立读写。任意一台关机或故障时，
直接访问另一台地址即可；恢复连接后自动双向补齐。**普通共享文件不参与同步**，
`SHARE_DIR` 始终是各自的本地目录。没有自动切换 IP 或统一网址。

双活使用本地 `data/clipboard_sync.sqlite3` 保存内容、逻辑版本、同步确认和删除标记。
Python 标准库 SQLite 事务提交后才返回本机保存成功。首次启用时导入原 JSON，
原文件另存为 `clipboard-imported.json`；此后 SQLite 是实际数据源。

- 正常联网时约每两秒检查同步，本地写入还会唤醒同步任务。
- 两边各自新增的条目合并；同一条目的并发编辑按逻辑版本号、节点名确定一致结果。
- 删除优先于编辑，同一 ID 的删除永久生效。删除标记不随 200 条显示上限清理。
- 一键清空删除本机当时已知的条目，对端离线期间新增、尚未见到的条目保留。
- 图片通过带密钥的接口传输，校验 SHA-256 后原子落盘，再提交记录与同步确认。
- 页面区分「本机已保存，等待同步」和「已同步到两台」，并显示另一台是否在线。
  同步确认表示该版本已在对端保存，不承诺对端今后永远在线或磁盘永不故障。
- 一台离线期间的新内容只有本机副本，若在补同步之前磁盘损坏，仍可能丢失。

启用前先备份，暂停两台服务，把当前权威副本的 JSON 和图片迁移到另一台，避免
用旧 JSON 重新带回已经删除的内容。通过 Git 提交、推送及两台 Pull 更新代码后，
在两台分别执行配置脚本（需要管理员权限）。两台使用不同节点名、同一同步密钥：

```bash
# NAS：CLIPBOARD_SYNC_TOKEN 从环境传入，不放进命令参数或 Git。
sudo --preserve-env=CLIPBOARD_SYNC_TOKEN python3 /opt/fileshare-lan/deploy/configure_dual.py \
  --node nas188 --peer http://192.168.31.193:8080
sudo systemctl restart fileshare-lan
```

```powershell
# Windows：先配置再启动既有 FileShareWeb 任务。
.venv\Scripts\python.exe deploy\configure_dual.py --node win193 --peer http://192.168.31.188:8080
Start-ScheduledTask -TaskName FileShareWeb
```

脚本保留已有端口、共享目录和备份配置，清除旧的主服务转发配置，并另存切换前
配置。同步接口使用专用 Bearer 密钥，密钥保存在不入 Git 的私密 `server.env` 中。

原有定时备份继续运行，改为各自备份本机。ZIP 包含当前 JSON 导出、图片和一致的
SQLite 快照，涵盖删除标记。NAS 每天备份保留 14 份，Windows 开机及每小时备份
保留 24 份。单台磁盘损坏时可从健康节点导出完整备份恢复，并保留各自节点配置。
误删时从旧备份取回内容后重新发布为新条目；直接恢复旧 ID 会再次收到对端删除
标记。需要整体回滚时，应暂停两台服务、保存当前数据，再将同一份完整备份恢复
到两台（含 `clipboard_sync.sqlite3` 和图片目录），之后重新启动。

验证双活及原有上传功能：

```bash
python3 -m unittest test_clipboard_dual test_clipboard_primary test_upload_integrity test_upload_permissions
```

### NAS 主服务与 Windows 剪切板入口

常年开机的 NAS 可以统一保存剪切板，Windows 保留原有网页入口。Windows 的所有
剪切板操作（含图片、搜索、编辑、删除）转发到 NAS，普通文件操作仍使用各自本机
的 `SHARE_DIR`。NAS 不可达时入口返回 503，不会向 Windows 本地剪切板写入。
这属于主服务加多个入口，不提供自动故障切换。剪切板页面可见时每两秒自动检查
更新，编辑文字时暂停刷新。

主服务继续使用本地 JSON 和图片目录，无需增加数据库。运行配置放在代码目录下
的 `server.env`（不入 Git），环境变量优先；也可用 `FILESHARE_CONFIG` 指定配置路径。

首次安装前通过 Git clone / pull 获取代码，并先迁移旧主机的 `clipboard.json` 和
`clipboard_files/`。迁移时暂停旧服务写入，保留迁移前备份，核对条目和图片后再
启用新入口。下面两个安装命令都需要管理员权限，并从环境变量
`CLIPBOARD_BACKUP_TOKEN` 读取同一随机密钥；不要把密钥放进 Git。

```bash
# NAS：数据目录应位于持久化数据盘；user 为可访问该目录的现有用户。
sudo --preserve-env=CLIPBOARD_BACKUP_TOKEN python3 /opt/fileshare-lan/deploy/install_lan.py \
  primary --host 192.168.31.188 --port 8080 \
  --user lindakun --data-root /vol1/1000/2_工作资料/ftp-server
```

```powershell
# Windows：在项目目录使用项目的 Python 安装入口配置及备份任务。
.venv\Scripts\python.exe deploy\install_lan.py gateway --host 0.0.0.0 --port 8080 `
  --primary-url http://192.168.31.188:8080
# 停止现有 FileShareWeb 进程后重新运行任务，让配置生效。
```

安装器创建配置、数据目录与服务定义，不会改写代码。已有 `server.env` 时会停止，
避免覆盖自定义配置。NAS 服务名为 `fileshare-lan`，备份定时器为
`fileshare-lan-backup.timer`；Windows 保留 `FileShareWeb`，新增
`FileShareClipboardBackup`。两台代码更新仍然只通过 Git Pull 完成。

备份通过带 Bearer 密钥的 `GET /api/clipboard/backup` 拉取，在剪切板锁内生成包含
JSON 和所引用图片的一致性 ZIP。备份先写临时文件，校验长度和 ZIP 后发布，失败时
不覆盖已有备份。NAS 每天北京时间 03:10 附近备份、保留 14 份；Windows 开机后
及运行期间每小时备份、保留 24 份，睡眠或关机期间无法备份。Windows 下次启动会
继续拉取。原始剪切板仍受 `CLIPBOARD_MAX_ENTRIES`（默认 200）限制。

NAS 备份目录为 `<data-root>/backups`，Windows 为 `<项目目录>/data/backups`。安装后
应立即执行一次备份，确认两台都能生成 ZIP。也可手动运行：

```bash
python3 clipboard_backup.py --url http://192.168.31.188:8080 --output /path/to/backups --keep 14
```

恢复时先停止主服务，将选定备份中的 `clipboard.json` 和 `clipboard_files/` 解压
到 `DATA_DIR`（先另存当前数据，使用新的图片目录），然后重启并核对条目和图片。
备份接口未配置密钥或密钥错误时返回 403；普通网页仍沿用现有的局域网无密码访问。
不要将服务端口转发到公网。

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
已有自定义配置会保留，旧默认上传上限 `2048` 会升级为 `4096`，并重启服务应用更新。

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
| `MAX_UPLOAD_MB` | `4096` | 单文件上传上限，`0` 表示不限制 |
| `CLIPBOARD_MAX_IMAGE_MB` | `20` | 剪切板单张图片上限 |
| `CLIPBOARD_MAX_ENTRIES` | `200` | 剪切板最多保留条数 |
| `CLIPBOARD_PRIMARY_URL` | 空 | 剪切板主服务地址；为空时使用本地存储 |
| `CLIPBOARD_BACKUP_TOKEN` | 空 | 备份接口密钥；为空时禁用备份接口 |
| `FILESHARE_CONFIG` | `<脚本目录>/server.env` | 本地运行配置文件路径 |
| `CLIPBOARD_NODE_ID` | 空 | 双活节点唯一名称；为空时保持原有单机或转发模式 |
| `CLIPBOARD_PEER_URL` | 空 | 剪切板双活对端地址 |
| `CLIPBOARD_SYNC_TOKEN` | 空 | 两台共同使用的专用同步密钥 |
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

- 网页版：看是不是超过了 `MAX_UPLOAD_MB` 上限（默认 4096MB）
- FTP 版：通常是被动模式端口被防火墙挡了，确认 60000-60100 已放行

**Q: 上传大文件失败 / 服务被重启？**

Linux 部署设了 `MemoryMax=256M`，进程超限会被 systemd 停止。正常文件上传是流式落盘，内存不会随文件大小线性增长。单文件超过 `MAX_UPLOAD_MB` 会被拒绝，不代表内存超限。Windows 不使用此 systemd 限制。

先检查单文件上限、磁盘空间和日志中的错误；网络中断时单文件最多自动重试两次。TCP 会重传丢失的数据包，短时抖动一般只影响速度。持续断网、休眠或服务重启仍会导致上传失败，当前没有断点续传。

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
