# -*- coding: utf-8 -*-
"""
局域网 HTTP 文件共享服务器（网页版）
浏览器直接访问 http://<本机IP>:8080 即可上传/下载/管理文件。

启动方式：
    python http_server.py
或双击 start_web.bat
按 Ctrl+C 停止。
"""

import json
import errno
import os
import re
import shutil
import socket
import sys
import tempfile
import urllib.parse
import zipfile
import mimetypes
import threading
import uuid
import hmac
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from server_config import load_config

load_config()

# ===== 配置区（可按需修改，均可用环境变量覆盖）=====

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

# 监听地址与端口。
# Linux/systemd 部署时设 HTTP_HOST=127.0.0.1 只绑本机，配合 SSH 隧道使用，不开公网。
HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
PORT = int(os.environ.get("HTTP_PORT", 8080))

# 共享文件目录（默认脚本同级 shared；服务器上建议指到 /var/lib/fileshare/shared）
SHARE_DIR = os.environ.get("SHARE_DIR") or os.path.join(BASE_DIR, "shared")

# 数据目录（剪贴板存储 + 上传中转），与 SHARE_DIR 解耦，便于代码与数据分离部署
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
CLIPBOARD_FILE = os.path.join(DATA_DIR, "clipboard.json")
CLIPBOARD_FILES_DIR = os.path.join(DATA_DIR, "clipboard_files")
# 上传中转目录：与 SHARE_DIR 同盘时用 os.replace 秒完成，避免跨盘拷贝大文件
SPOOL_DIR = os.path.join(DATA_DIR, ".spool")

# 单文件上传上限（MB），0 = 不限制。超限的文件会被拒绝并丢弃。
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", 4096))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024 if MAX_UPLOAD_MB > 0 else 0

CLIPBOARD_MAX_ENTRIES = int(os.environ.get("CLIPBOARD_MAX_ENTRIES", 200))
CLIPBOARD_MAX_TEXT = 100 * 1024
# 剪贴板图片大小上限（MB），防止单张图把内存打满
CLIPBOARD_MAX_IMAGE_MB = int(os.environ.get("CLIPBOARD_MAX_IMAGE_MB", 20))
CLIPBOARD_MAX_IMAGE = CLIPBOARD_MAX_IMAGE_MB * 1024 * 1024
clipboard_lock = threading.Lock()
CLIPBOARD_PRIMARY_URL = os.environ.get("CLIPBOARD_PRIMARY_URL", "").rstrip("/")
CLIPBOARD_BACKUP_TOKEN = os.environ.get("CLIPBOARD_BACKUP_TOKEN", "")
# 限制同时落盘的上传数，避免多个页面同时上传抢占磁盘。
upload_slots = threading.BoundedSemaphore(2)

# 文件 IO 分块大小（流式读写用）
CHUNK_SIZE = 64 * 1024

# ==============================


def get_local_ip():
    """获取本机局域网 IP，优先返回真实物理网卡 IP，跳过 VPN/虚拟网卡。"""
    import subprocess

    # 虚拟/回环网卡前缀，这些 IP 不是真实局域网地址
    # 127.x = 回环; 169.254.x = 未获取 DHCP; 198.18.x = 性能测试/VPN 虚拟网卡
    virtual_prefixes = ("127.", "169.254.", "198.18.")
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["ipconfig"], capture_output=True, timeout=3
            ).stdout.decode("gbk", errors="ignore")
            ips = re.findall(r"IPv4[^\d]*([\d.]+)", out)
        elif sys.platform == "darwin":
            # macOS 没有 ip 命令，用 ifconfig（只取 inet，排除 inet6）
            out = subprocess.run(
                ["ifconfig"], capture_output=True, timeout=3
            ).stdout.decode(errors="ignore")
            ips = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        else:
            out = subprocess.run(
                ["ip", "-4", "addr"], capture_output=True, timeout=3
            ).stdout.decode(errors="ignore")
            ips = re.findall(r"inet ([\d.]+)", out)
        lan_ips = [ip for ip in ips if not ip.startswith(virtual_prefixes)]
        if lan_ips:
            return lan_ips[0]
        if ips:
            return ips[0]
    except Exception:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def safe_join(base, *paths):
    """安全拼接路径，防止路径穿越（../ 攻击），返回绝对路径或 None。"""
    base = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base, *paths))
    if target == base or target.startswith(base + os.sep):
        return target
    return None


def clean_rel_path(raw):
    """清洗上传文件携带的相对路径，返回 `a/b/c.txt` 形式的安全相对路径。

    兼容三种来源：
      - 普通上传：只有文件名
      - 文件夹上传（webkitdirectory / webkitRelativePath）：a/b/c.txt
      - 拖拽目录或 Windows 来源：a\\b\\c.txt、C:\\x\\y.txt

    丢弃空段、`.`、`..` 与控制字符，因此 `../../etc/passwd` 会被压成 `etc/passwd`，
    永远逃不出共享根目录。返回 None 表示没有可用路径。
    """
    if not raw:
        return None
    s = raw.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", s):  # 去掉 Windows 盘符
        s = s[2:]
    parts = []
    for seg in s.split("/"):
        # 去掉控制字符与路径分隔符本身
        seg = "".join(ch for ch in seg if ch >= " " and ch not in "/\\")
        seg = seg.strip()
        if not seg or seg in (".", ".."):
            continue
        parts.append(seg)
    return "/".join(parts) if parts else None


def unique_path(path):
    """目标路径若已被同名目录占用，追加后缀避让，避免覆盖失败。"""
    if not os.path.isdir(path):
        return path
    d = os.path.dirname(path)
    stem, ext = os.path.splitext(os.path.basename(path))
    for i in range(1, 100):
        cand = os.path.join(d, f"{stem} (文件{i}){ext}")
        if not os.path.exists(cand):
            return cand
    return path


def human_size(size):
    """把字节数转成人类可读大小。"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def ensure_data_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(CLIPBOARD_FILES_DIR, exist_ok=True)
    os.makedirs(SPOOL_DIR, exist_ok=True)


def cleanup_spool():
    """清理上次遗留的上传中转临时文件（进程异常退出时可能残留）。"""
    try:
        for name in os.listdir(SPOOL_DIR):
            try:
                os.remove(os.path.join(SPOOL_DIR, name))
            except OSError:
                pass
    except OSError:
        pass


def _load_clipboard():
    try:
        with open(CLIPBOARD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _save_clipboard(entries):
    tmp = CLIPBOARD_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CLIPBOARD_FILE)


def _ext_from_mime(mime):
    return mimetypes.guess_extension(mime or "") or ".bin"


def _clipboard_add(entry):
    with clipboard_lock:
        entries = _load_clipboard()
        entries.append(entry)
        if len(entries) > CLIPBOARD_MAX_ENTRIES:
            removed = entries[:-CLIPBOARD_MAX_ENTRIES]
            for r in removed:
                if r.get("type") == "image":
                    try:
                        os.remove(os.path.join(CLIPBOARD_FILES_DIR, r["id"] + _ext_from_mime(r.get("mime"))))
                    except OSError:
                        pass
            entries = entries[-CLIPBOARD_MAX_ENTRIES:]
        _save_clipboard(entries)
    return entry


class FileHandler(BaseHTTPRequestHandler):
    """HTTP 文件管理请求处理器。"""

    server_version = "FileShare/1.0"
    # 单次 socket 读超时（秒），防止慢连接长期占着线程
    timeout = 600

    def log_message(self, format, *args):
        """简化日志格式。"""
        print(f"[{self.log_date_time_string()}] {self.client_address[0]} {format % args}")

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text, code=200):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/clipboard/backup":
            self._api_clipboard_backup()
            return
        if self._proxy_clipboard(path):
            return

        if path == "/" or path == "/index.html":
            self._serve_index()
        elif path == "/api/list":
            self._api_list(parsed.query)
        elif path.startswith("/api/download/"):
            self._api_download(path[len("/api/download/"):])
        elif path == "/api/clipboard":
            self._api_clipboard_list(parsed.query)
        elif path.startswith("/api/clipboard/file/"):
            self._api_clipboard_file(path[len("/api/clipboard/file/"):])
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if self._proxy_clipboard(path):
            return

        if path == "/api/upload":
            self._api_upload()
        elif path == "/api/mkdir":
            self._api_mkdir()
        elif path == "/api/delete":
            self._api_delete()
        elif path == "/api/rename":
            self._api_rename()
        elif path == "/api/download-zip":
            self._api_download_zip()
        elif path == "/api/clipboard":
            self._api_clipboard_add()
        elif path == "/api/clipboard/image":
            self._api_clipboard_add_image()
        elif path == "/api/clipboard/clear":
            self._api_clipboard_clear()
        elif path == "/api/clipboard/edit":
            self._api_clipboard_edit()
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self._proxy_clipboard(path):
            return
        if path.startswith("/api/clipboard/"):
            cid = path[len("/api/clipboard/"):]
            if cid:
                self._api_clipboard_delete(cid)
            else:
                self._send_json({"error": "缺少 id"}, 400)
        else:
            self._send_json({"error": "Not Found"}, 404)

    # ---- GET 处理 ----

    def _serve_index(self):
        index_path = os.path.join(WEB_DIR, "index.html")
        if os.path.isfile(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                self._send_html(f.read())
        else:
            self._send_html("<h1>web/index.html 不存在</h1>", 404)

    def _api_list(self, query):
        """列出指定目录下的文件。query: path=<相对路径>"""
        params = urllib.parse.parse_qs(query)
        rel_path = params.get("path", [""])[0]
        target = safe_join(SHARE_DIR, rel_path)
        if target is None or not os.path.isdir(target):
            self._send_json({"error": "无效目录"}, 400)
            return

        items = []
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            items.append({
                "name": name,
                "is_dir": os.path.isdir(full),
                "size": st.st_size if os.path.isfile(full) else 0,
                "size_text": human_size(st.st_size) if os.path.isfile(full) else "-",
                "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })

        # 构建上级目录路径
        parent = os.path.dirname(rel_path.rstrip("/")) if rel_path else ""
        if rel_path and not rel_path.endswith("/"):
            parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""

        self._send_json({
            "path": rel_path,
            "parent": parent if rel_path else "",
            "items": items,
        })

    def _api_download(self, rel_path):
        """下载文件（流式发送，不把整个文件读进内存）。"""
        rel_path = urllib.parse.unquote(rel_path)
        target = safe_join(SHARE_DIR, rel_path)
        if target is None or not os.path.isfile(target):
            self._send_json({"error": "文件不存在"}, 404)
            return

        filename = os.path.basename(target)
        try:
            size = os.path.getsize(target)
        except OSError as e:
            self._send_json({"error": str(e)}, 500)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        # RFC 5987 处理中文文件名
        encoded = urllib.parse.quote(filename)
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded}")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        try:
            with open(target, "rb") as f:
                shutil.copyfileobj(f, self.wfile, CHUNK_SIZE)
        except (OSError, BrokenPipeError, ConnectionResetError):
            pass  # 客户端中断，正常现象

    # ---- 流式 multipart 解析 ----
    # 手写流式解析：大文件边收边落盘，内存占用与文件大小无关。
    # 原实现 body = rfile.read(content_length) 会把整个文件吃进内存，
    # 在小内存服务器上（如 1GB 实例）上传大文件会触发 OOM。

    @staticmethod
    def _pump_until(buf, fill, sep, tail_keep, sink, limit=0):
        """把 buf 内容流式吐给 sink，直到遇到分隔符 sep。

        返回 (写入字节数, 是否超限)。
        buf 是滑动缓冲；tail_keep 保证分隔符跨 chunk 时不被切断。
        """
        written = 0
        while True:
            idx = buf.find(sep)
            if idx != -1:
                if limit and written + idx > limit:
                    return written, True
                sink(bytes(buf[:idx]))
                written += idx
                del buf[:idx + len(sep)]
                return written, False
            # 没遇到分隔符：吐掉除尾部保留区外的内容
            if len(buf) > tail_keep:
                cut = len(buf) - tail_keep
                sink(bytes(buf[:cut]))
                written += cut
                del buf[:cut]
                if limit and written > limit:
                    return written, True
            if not fill():
                raise ValueError("上传数据不完整，未收到文件结束边界，请重新上传")

    def _iter_multipart(self, boundary, content_length, max_file_bytes=None):
        """流式解析 multipart/form-data，逐个 yield (headers_text, kind, value)。

        kind == "file"  → value = (临时文件路径, 原始文件名, 字节数, 是否超限)
        kind == "field" → value = bytes
        调用方负责删除临时文件。max_file_bytes 为单文件上限，None 取全局配置。
        """
        limit = MAX_UPLOAD_BYTES if max_file_bytes is None else max_file_bytes
        delim = b"--" + boundary.encode()
        CRLF = b"\r\n"
        tail_keep = len(delim) + 8

        buf = bytearray()
        remaining = [content_length]

        def fill():
            if remaining[0] <= 0:
                return False
            chunk = self.rfile.read(min(CHUNK_SIZE, remaining[0]))
            if not chunk:
                raise ValueError("上传连接提前断开，请重新上传")
            remaining[0] -= len(chunk)
            buf.extend(chunk)
            return True

        def check_part_end():
            # 发布文件前确认下一个边界有效，最后一段还要收齐声明的请求长度。
            while len(buf) < 2:
                if not fill():
                    raise ValueError("上传结束边界不完整")
            if buf[:2] == b"--":
                while remaining[0]:
                    if len(buf) > 4:
                        raise ValueError("上传结束边界格式错误")
                    fill()
                if bytes(buf) not in (b"--", b"--\r\n"):
                    raise ValueError("上传结束边界格式错误")
            elif buf[:2] != CRLF:
                raise ValueError("上传分段边界格式错误")

        # 1) 定位第一个 boundary
        while buf.find(delim) == -1:
            if len(buf) > CHUNK_SIZE:
                raise ValueError("上传起始边界无效")
            if not fill():
                raise ValueError("上传起始边界缺失")
        del buf[:buf.find(delim) + len(delim)]

        while True:
            # 2) 判断是结束标记 "--" 还是下一个 part 的 CRLF
            while len(buf) < 2:
                if not fill():
                    raise ValueError("上传结束边界不完整")
            if bytes(buf[:2]) == b"--":
                check_part_end()
                return
            if bytes(buf[:2]) != CRLF:
                raise ValueError("上传分段边界格式错误")
            del buf[:2]

            # 3) 读 part 头部
            while buf.find(CRLF + CRLF) == -1:
                if len(buf) > CHUNK_SIZE:
                    raise ValueError("上传分段头部过大")
                if not fill():
                    raise ValueError("上传分段头部不完整")
            hdr_end = buf.find(CRLF + CRLF)
            headers_text = bytes(buf[:hdr_end]).decode("utf-8", errors="ignore")
            del buf[:hdr_end + 4]

            filename = None
            for line in headers_text.split("\r\n"):
                if "filename=" in line:
                    m = re.search(r'filename="([^"]*)"', line)
                    if m:
                        filename = m.group(1)

            sep = CRLF + delim

            if filename is not None and filename != "":
                # 文件字段：流式落盘到中转目录
                fd, tmp_path = tempfile.mkstemp(prefix="up_", dir=SPOOL_DIR)
                try:
                    with os.fdopen(fd, "wb") as fh:
                        written, too_big = self._pump_until(
                            buf, fill, sep, tail_keep, fh.write, limit
                        )
                    if too_big:
                        # 超限：消费剩余内容，保证后续文件仍可解析。
                        self._pump_until(buf, fill, sep, tail_keep, lambda b: None)
                    check_part_end()
                except BaseException:
                    # 尚未 yield 的文件也必须清理，包括断流、超时和磁盘写入失败。
                    os.remove(tmp_path)
                    raise
                yield headers_text, "file", (tmp_path, filename, written, too_big)
            else:
                # 普通字段（dir 等）：内容很小，直接累到内存
                val = bytearray()
                _, too_big = self._pump_until(
                    buf, fill, sep, tail_keep, val.extend, CLIPBOARD_MAX_TEXT
                )
                if too_big:
                    raise ValueError("上传表单字段过大")
                check_part_end()
                yield headers_text, "field", bytes(val)

    def _save_upload(self, tmp_path, raw_name, rel_dir):
        """把中转文件搬进共享目录，保留上传时的相对路径结构。

        raw_name 形如 `file.txt`（普通上传）或 `dir/sub/file.txt`（文件夹上传），
        rel_dir 是本次上传的目标根目录。返回落盘后的相对路径，失败返回 None。
        同盘时用 os.replace，是瞬时 rename，不产生额外拷贝。
        """
        rel = clean_rel_path(raw_name)
        if not rel:
            return None
        base_rel = clean_rel_path(rel_dir) or ""
        target_path = safe_join(SHARE_DIR, base_rel, *rel.split("/"))
        if target_path is None:
            return None
        target_dir = os.path.dirname(target_path)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError:
            return None
        target_path = unique_path(target_path)
        # mkstemp 默认是 0600；正式发布前开放共享文件读取，避免曲库扫描首次访问被拒绝。
        # 保留中转期间的私有权限，跨盘搬运也会继承这里设置的权限。
        os.chmod(tmp_path, 0o644)
        try:
            os.replace(tmp_path, target_path)
        except OSError as e:
            if e.errno != errno.EXDEV and getattr(e, "winerror", None) != 17:
                raise
            # 跨盘先复制到目标盘临时文件，完成后发布，避免失败覆盖原文件。
            fd, staged = tempfile.mkstemp(prefix="up_", dir=target_dir)
            os.close(fd)
            try:
                shutil.copyfile(tmp_path, staged)
                os.chmod(staged, 0o644)
                os.replace(staged, target_path)
                os.remove(tmp_path)
            finally:
                if os.path.exists(staged):
                    os.remove(staged)
        return os.path.relpath(target_path, SHARE_DIR).replace(os.sep, "/")

    # ---- POST 处理 ----

    def _api_upload(self):
        """处理文件上传（multipart/form-data）。"""
        if not upload_slots.acquire(blocking=False):
            self.close_connection = True
            self._send_json({"error": "正在处理其他上传，请稍后重试"}, 503)
            return
        try:
            self._handle_upload()
        finally:
            upload_slots.release()

    def _handle_upload(self):
        # 未读完请求体时关闭连接，防止残余数据被解释成下一条请求。
        self.close_connection = True
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send_json({"error": "需 multipart 上传"}, 400)
            return

        # 解析 boundary
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip('"')
                break
        if not boundary or len(boundary) > 200:
            self._send_json({"error": "缺少 boundary"}, 400)
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"error": "请求长度无效"}, 400)
            return
        if content_length <= 0:
            self._send_json({"error": "请求体为空"}, 400)
            return

        uploaded = []
        oversize = []
        skipped = []
        tmp_files = []
        rel_dir = ""  # dir 字段可能在前面的 part，需跨 part 保留

        try:
            # 同盘不会重复占用整份文件；跨盘则两边都要能容纳当前请求。
            for directory in (SPOOL_DIR, SHARE_DIR):
                if shutil.disk_usage(directory).free < content_length + 64 * 1024 * 1024:
                    self._send_json({"error": "磁盘可用空间不足，请清理后重新上传"}, 507)
                    return
            for headers_text, kind, value in self._iter_multipart(boundary, content_length):
                if kind == "field":
                    if 'name="dir"' in headers_text:
                        rel_dir = value.decode("utf-8", errors="ignore").strip()
                    continue

                tmp_path, filename, size, too_big = value
                tmp_files.append(tmp_path)
                rel_name = clean_rel_path(filename)
                if too_big:
                    oversize.append(rel_name or "?")
                    continue
                saved = self._save_upload(tmp_path, filename, rel_dir)
                if saved is None:
                    skipped.append(rel_name or "?")
                    continue
                tmp_files.remove(tmp_path)
                uploaded.append(saved)
        except socket.timeout:
            self._send_json({"error": "上传连接连续 10 分钟没有数据，请重新上传"}, 408)
            return
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
            return
        except Exception as e:
            self._send_json({"error": f"上传失败: {e}"}, 500)
            return
        finally:
            for p in tmp_files:
                try:
                    os.remove(p)
                except OSError:
                    pass

        if not uploaded and oversize:
            self._send_json(
                {"error": f"文件超过上限 {MAX_UPLOAD_MB}MB：{', '.join(oversize[:5])}"}, 413
            )
            return

        resp = {
            "uploaded": uploaded[:500],
            "count": len(uploaded),
            "dir": clean_rel_path(rel_dir) or "",
        }
        if len(uploaded) > 500:
            resp["truncated"] = True
        if oversize:
            resp["oversize"] = oversize[:50]
        if skipped:
            resp["skipped"] = skipped[:50]
        self._send_json(resp)

    def _api_mkdir(self):
        """创建目录。body: {"path": "...", "name": "..."}"""
        data = self._read_json_body()
        if data is None:
            return
        rel_dir = data.get("path", "")
        name = os.path.basename(data.get("name", ""))
        if not name:
            self._send_json({"error": "目录名不能为空"}, 400)
            return
        target = safe_join(SHARE_DIR, rel_dir, name)
        if target is None:
            self._send_json({"error": "无效路径"}, 400)
            return
        try:
            os.makedirs(target, exist_ok=False)
            self._send_json({"ok": True})
        except FileExistsError:
            self._send_json({"error": "目录已存在"}, 400)
        except OSError as e:
            self._send_json({"error": str(e)}, 500)

    def _api_delete(self):
        """删除文件或目录。body: {"path": "..."}"""
        data = self._read_json_body()
        if data is None:
            return
        rel_path = data.get("path", "")
        target = safe_join(SHARE_DIR, rel_path)
        if target is None or not os.path.exists(target):
            self._send_json({"error": "路径不存在"}, 404)
            return
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
            self._send_json({"ok": True})
        except OSError as e:
            self._send_json({"error": str(e)}, 500)

    def _api_rename(self):
        """重命名。body: {"path": "...", "name": "新名字"}"""
        data = self._read_json_body()
        if data is None:
            return
        rel_path = data.get("path", "")
        new_name = os.path.basename(data.get("name", ""))
        if not new_name:
            self._send_json({"error": "新名字不能为空"}, 400)
            return
        target = safe_join(SHARE_DIR, rel_path)
        if target is None or not os.path.exists(target):
            self._send_json({"error": "原路径不存在"}, 404)
            return
        new_path = os.path.join(os.path.dirname(target), new_name)
        try:
            os.rename(target, new_path)
            self._send_json({"ok": True})
        except OSError as e:
            self._send_json({"error": str(e)}, 500)

    def _api_download_zip(self):
        """批量下载：把多个文件/文件夹打包成 zip。body: {"paths": ["file1", "dir/file2"]}"""
        data = self._read_json_body()
        if data is None:
            return
        paths = data.get("paths", [])
        if not paths:
            self._send_json({"error": "未选择文件"}, 400)
            return

        # 收集所有有效路径
        valid = []
        for rel in paths:
            target = safe_join(SHARE_DIR, rel)
            if target and os.path.exists(target):
                valid.append((rel, target))
        if not valid:
            self._send_json({"error": "无有效文件"}, 404)
            return

        # 打包成 zip：先写中转文件再流式发送，避免整个 zip 常驻内存
        tmp_zip = None
        try:
            fd, tmp_zip = tempfile.mkstemp(suffix=".zip", prefix="zip_", dir=SPOOL_DIR)
            with os.fdopen(fd, "wb") as fh:
                with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as zf:
                    for rel, target in valid:
                        if os.path.isdir(target):
                            # 文件夹：递归添加，保留相对路径结构
                            for root, dirs, files in os.walk(target):
                                for fn in files:
                                    full = os.path.join(root, fn)
                                    arcname = os.path.relpath(full, SHARE_DIR)
                                    zf.write(full, arcname)
                        else:
                            # 单文件：用文件名作为 zip 内路径
                            zf.write(target, os.path.basename(target))

            size = os.path.getsize(tmp_zip)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="files.zip"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(tmp_zip, "rb") as f:
                shutil.copyfileobj(f, self.wfile, CHUNK_SIZE)
        except (OSError, BrokenPipeError, ConnectionResetError):
            pass  # 客户端中断或磁盘异常
        finally:
            if tmp_zip:
                try:
                    os.remove(tmp_zip)
                except OSError:
                    pass

    # ---- 共享剪切板 API ----

    def _proxy_clipboard(self, path):
        """入口节点只访问主服务，失败时不写入本地剪切板。"""
        if not CLIPBOARD_PRIMARY_URL or not (
                path == "/api/clipboard" or path.startswith("/api/clipboard/")):
            return False
        if path == "/api/clipboard/backup":
            self._send_json({"error": "备份请直接访问主服务"}, 403)
            return True
        if self.headers.get("Transfer-Encoding"):
            self._send_json({"error": "不支持分块请求体"}, 400)
            return True
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "无效 Content-Length"}, 400)
            return True
        limit = (CLIPBOARD_MAX_IMAGE + 16384 if path == "/api/clipboard/image"
                 else CLIPBOARD_MAX_TEXT * 6 + 16384)
        if length < 0 or length > limit:
            self._send_json({"error": "剪切板请求体超过上限"}, 413)
            return True
        started = False
        try:
            body = self.rfile.read(length) if length else None
            if length and len(body) != length:
                self._send_json({"error": "请求体不完整"}, 400)
                return True
            headers = {}
            if self.headers.get("Content-Type"):
                headers["Content-Type"] = self.headers["Content-Type"]
            request = urllib.request.Request(CLIPBOARD_PRIMARY_URL + self.path,
                                             data=body, headers=headers, method=self.command)
            # 不重试写请求，避免响应丢失时重复发布。
            try:
                response = urllib.request.urlopen(request, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                self.send_response(response.code)
                for name in ("Content-Type", "Content-Length"):
                    if response.headers.get(name):
                        self.send_header(name, response.headers[name])
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                started = True
                shutil.copyfileobj(response, self.wfile, CHUNK_SIZE)
        except (OSError, urllib.error.URLError):
            if started:
                self.close_connection = True
            else:
                self._send_json({"error": "NAS 剪切板主服务暂时不可用，请稍后重试"}, 503)
        return True

    def _api_clipboard_backup(self):
        """在同一把锁内打包元数据和图片，生成一致的备份。"""
        token = self.headers.get("Authorization", "")
        if (CLIPBOARD_PRIMARY_URL or not CLIPBOARD_BACKUP_TOKEN or
                not hmac.compare_digest(token.encode(),
                                        ("Bearer " + CLIPBOARD_BACKUP_TOKEN).encode())):
            self._send_json({"error": "备份访问未授权"}, 403)
            return
        with tempfile.TemporaryFile(dir=DATA_DIR) as snapshot:
            with clipboard_lock:
                entries = _load_clipboard()
                with zipfile.ZipFile(snapshot, "w", zipfile.ZIP_STORED) as archive:
                    archive.writestr("clipboard.json", json.dumps(entries, ensure_ascii=False))
                    for entry in entries:
                        if entry.get("type") == "image":
                            name = entry["id"] + _ext_from_mime(entry.get("mime"))
                            archive.write(os.path.join(CLIPBOARD_FILES_DIR, name),
                                          "clipboard_files/" + name)
            size = snapshot.tell()
            snapshot.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            shutil.copyfileobj(snapshot, self.wfile, CHUNK_SIZE)

    def _api_clipboard_list(self, query):
        """列出剪贴板条目。query 可带 q=<关键词> 做服务端过滤（仅匹配文字条目）。"""
        params = urllib.parse.parse_qs(query)
        q = (params.get("q", [""])[0] or "").strip().lower()
        with clipboard_lock:
            entries = _load_clipboard()
        if q:
            entries = [e for e in entries
                       if e.get("type") == "text" and q in (e.get("text") or "").lower()]
        self._send_json({"items": list(reversed(entries))})

    def _api_clipboard_edit(self):
        """编辑已发布的文字条目。body: {"id": "...", "text": "..."}"""
        data = self._read_json_body()
        if data is None:
            return
        cid = data.get("id", "")
        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            self._send_json({"error": "内容不能为空"}, 400)
            return
        if len(text.encode("utf-8")) > CLIPBOARD_MAX_TEXT:
            self._send_json({"error": f"内容过大（上限 {CLIPBOARD_MAX_TEXT // 1024}KB）"}, 400)
            return
        with clipboard_lock:
            entries = _load_clipboard()
            target = next((e for e in entries if e.get("id") == cid), None)
            if not target:
                self._send_json({"error": "条目不存在"}, 404)
                return
            if target.get("type") != "text":
                self._send_json({"error": "仅支持编辑文字条目"}, 400)
                return
            target["text"] = text
            target["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _save_clipboard(entries)
            updated = dict(target)
        self._send_json({"ok": True, "entry": updated})

    def _api_clipboard_add(self):
        data = self._read_json_body()
        if data is None:
            return
        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            self._send_json({"error": "内容不能为空"}, 400)
            return
        if len(text.encode("utf-8")) > CLIPBOARD_MAX_TEXT:
            self._send_json({"error": f"内容过大（上限 {CLIPBOARD_MAX_TEXT // 1024}KB）"}, 400)
            return
        entry = {
            "id": uuid.uuid4().hex,
            "type": "text",
            "text": text,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _clipboard_add(entry)
        self._send_json({"ok": True, "entry": entry})

    def _api_clipboard_add_image(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send_json({"error": "需 multipart 上传"}, 400)
            return
        boundary = None
        for part in ctype.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[len("boundary="):].strip('"')
                break
        if not boundary:
            self._send_json({"error": "缺少 boundary"}, 400)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json({"error": "请求体为空"}, 400)
            return
        # 图片有体积上限，超限直接拒收
        if content_length > CLIPBOARD_MAX_IMAGE + 16384:
            self._send_json(
                {"error": f"图片过大（上限 {CLIPBOARD_MAX_IMAGE_MB}MB）"}, 413
            )
            return

        img_data = None
        mime = "image/png"
        tmp_files = []
        try:
            for headers_text, kind, value in self._iter_multipart(
                boundary, content_length, max_file_bytes=CLIPBOARD_MAX_IMAGE
            ):
                if kind != "file":
                    continue
                tmp_path, filename, size, too_big = value
                tmp_files.append(tmp_path)
                if too_big:
                    break
                mime = mimetypes.guess_type(filename or "")[0] or "image/png"
                with open(tmp_path, "rb") as f:
                    img_data = f.read()
                break
        except Exception as e:
            self._send_json({"error": f"图片上传失败: {e}"}, 500)
            return
        finally:
            for p in tmp_files:
                try:
                    os.remove(p)
                except OSError:
                    pass

        if not img_data:
            self._send_json({"error": f"未找到图片数据或图片超过 {CLIPBOARD_MAX_IMAGE_MB}MB"}, 400)
            return
        cid = uuid.uuid4().hex
        ext = mimetypes.guess_extension(mime) or ".png"
        fpath = os.path.join(CLIPBOARD_FILES_DIR, cid + ext)
        with open(fpath, "wb") as f:
            f.write(img_data)
        entry = {
            "id": cid,
            "type": "image",
            "mime": mime,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _clipboard_add(entry)
        self._send_json({"ok": True, "entry": entry})

    def _api_clipboard_delete(self, cid):
        with clipboard_lock:
            entries = _load_clipboard()
            target = next((e for e in entries if e.get("id") == cid), None)
            if not target:
                self._send_json({"error": "条目不存在"}, 404)
                return
            if target.get("type") == "image":
                try:
                    os.remove(os.path.join(CLIPBOARD_FILES_DIR, target["id"] + _ext_from_mime(target.get("mime"))))
                except OSError:
                    pass
            new_entries = [e for e in entries if e.get("id") != cid]
            _save_clipboard(new_entries)
        self._send_json({"ok": True})

    def _api_clipboard_clear(self):
        with clipboard_lock:
            entries = _load_clipboard()
            for e in entries:
                if e.get("type") == "image":
                    try:
                        os.remove(os.path.join(CLIPBOARD_FILES_DIR, e["id"] + _ext_from_mime(e.get("mime"))))
                    except OSError:
                        pass
            _save_clipboard([])
        self._send_json({"ok": True})

    def _api_clipboard_file(self, cid):
        with clipboard_lock:
            entries = _load_clipboard()
        entry = next((e for e in entries if e.get("id") == cid and e.get("type") == "image"), None)
        if not entry:
            self._send_json({"error": "图片不存在"}, 404)
            return
        ext = _ext_from_mime(entry.get("mime"))
        fpath = os.path.join(CLIPBOARD_FILES_DIR, entry["id"] + ext)
        if not os.path.isfile(fpath):
            self._send_json({"error": "图片文件丢失"}, 404)
            return
        try:
            with open(fpath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", entry.get("mime", "image/png"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            self._send_json({"error": str(e)}, 500)

    def _read_json_body(self):
        """读取并解析 JSON 请求体。"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json({"error": "请求体为空"}, 400)
            return None
        try:
            body = self.rfile.read(content_length)
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json({"error": f"JSON 解析失败: {e}"}, 400)
            return None


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    # 后台运行（pythonw.exe 无窗口）时，把输出重定向到日志文件
    if sys.executable.endswith("pythonw.exe"):
        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "server.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
        print(f"\n{'='*52}\n[{datetime.now()}] 服务启动（后台模式）\n{'='*52}")

    os.makedirs(SHARE_DIR, exist_ok=True)
    os.makedirs(WEB_DIR, exist_ok=True)
    ensure_data_dirs()
    cleanup_spool()

    server = ThreadingHTTPServer((HOST, PORT), FileHandler)

    ip = get_local_ip()
    loopback_only = HOST in ("127.0.0.1", "localhost", "::1")
    print("=" * 52)
    print("  HTTP 文件共享服务器已启动（网页版）")
    print("=" * 52)
    print(f"  监听地址   : {HOST}:{PORT}" + ("（仅本机，未开公网）" if loopback_only else ""))
    print(f"  共享目录   : {SHARE_DIR}")
    print(f"  数据目录   : {DATA_DIR}")
    print(f"  上传上限   : {str(MAX_UPLOAD_MB) + ' MB' if MAX_UPLOAD_MB else '不限'}")
    print(f"  权限       : 上传 + 下载 + 删除")
    print("=" * 52)
    if loopback_only:
        print("  已绑定回环地址，需通过 SSH 隧道访问。本机执行：")
        print(f"    ssh -N -L {PORT}:127.0.0.1:{PORT} <你的服务器别名>")
        print(f"  然后浏览器打开 http://127.0.0.1:{PORT}")
    else:
        print("  同一局域网内的设备用浏览器打开：")
        print(f"    http://{ip}:{PORT}")
    print("-" * 52)
    print("  按 Ctrl+C 停止服务器")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止，拜拜~")
        server.shutdown()


if __name__ == "__main__":
    main()
