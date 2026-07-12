# -*- coding: utf-8 -*-
"""
局域网 HTTP 文件共享服务器（网页版）
浏览器直接访问 http://<本机IP>:8080 即可上传/下载/管理文件。

启动方式：
    python http_server.py
或双击 start_web.bat
按 Ctrl+C 停止。
"""

import html
import io
import json
import os
import re
import shutil
import socket
import sys
import urllib.parse
import zipfile
import mimetypes
import threading
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ===== 配置区（可按需修改）=====

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARE_DIR = os.path.join(BASE_DIR, "shared")
WEB_DIR = os.path.join(BASE_DIR, "web")

HOST = "0.0.0.0"
PORT = int(os.environ.get("HTTP_PORT", 8080))

# 共享剪切板数据存储
DATA_DIR = os.path.join(BASE_DIR, "data")
CLIPBOARD_FILE = os.path.join(DATA_DIR, "clipboard.json")
CLIPBOARD_FILES_DIR = os.path.join(DATA_DIR, "clipboard_files")
CLIPBOARD_MAX_ENTRIES = 200
CLIPBOARD_MAX_TEXT = 100 * 1024
clipboard_lock = threading.Lock()

# ==============================


def get_local_ip():
    """获取本机局域网 IP，优先返回真实物理网卡 IP，跳过 VPN/虚拟网卡。"""
    import subprocess

    virtual_prefixes = ("127.", "169.254.", "198.18.")
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["ipconfig"], capture_output=True, timeout=3
            ).stdout.decode("gbk", errors="ignore")
            ips = re.findall(r"IPv4[^\d]*([\d.]+)", out)
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

        if path == "/" or path == "/index.html":
            self._serve_index()
        elif path == "/api/list":
            self._api_list(parsed.query)
        elif path.startswith("/api/download/"):
            self._api_download(path[len("/api/download/"):])
        elif path == "/api/clipboard":
            self._api_clipboard_list()
        elif path.startswith("/api/clipboard/file/"):
            self._api_clipboard_file(path[len("/api/clipboard/file/"):])
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

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
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
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
        """下载文件。"""
        rel_path = urllib.parse.unquote(rel_path)
        target = safe_join(SHARE_DIR, rel_path)
        if target is None or not os.path.isfile(target):
            self._send_json({"error": "文件不存在"}, 404)
            return

        filename = os.path.basename(target)
        try:
            with open(target, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            # RFC 5987 处理中文文件名
            encoded = urllib.parse.quote(filename)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded}")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            self._send_json({"error": str(e)}, 500)

    # ---- POST 处理 ----

    def _api_upload(self):
        """处理文件上传（multipart/form-data）。"""
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
        if not boundary:
            self._send_json({"error": "缺少 boundary"}, 400)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # 简单解析 multipart
        delimiter = b"--" + boundary.encode()
        parts = body.split(delimiter)
        uploaded = []
        rel_dir = ""  # dir 字段可能在前面的 part，需跨 part 保留

        for part in parts:
            if not part or part == b"--\r\n" or part == b"--\r\n--" or part.strip() == b"--":
                continue
            if part.startswith(b"\r\n"):
                part = part[2:]
            if part.endswith(b"\r\n"):
                part = part[:-2]

            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            header_bytes = part[:header_end].decode("utf-8", errors="ignore")
            content = part[header_end + 4:]

            # 提取文件名
            filename = None
            for line in header_bytes.split("\r\n"):
                if "filename=" in line:
                    m = re.search(r'filename="([^"]*)"', line)
                    if m:
                        filename = m.group(1)

            # dir 字段是单独的 part
            if not filename:
                if 'name="dir"' in header_bytes:
                    rel_dir = content.decode("utf-8", errors="ignore").strip()
                continue

            # 文件 part：用前面解析到的 rel_dir
            filename = os.path.basename(filename)
            if not filename:
                continue

            target_dir = safe_join(SHARE_DIR, rel_dir) or SHARE_DIR
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, filename)

            with open(target_path, "wb") as f:
                f.write(content)
            uploaded.append(filename)

        self._send_json({"uploaded": uploaded, "count": len(uploaded)})

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

        # 打包成 zip（内存中）
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
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

        zip_data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", 'attachment; filename="files.zip"')
        self.send_header("Content-Length", str(len(zip_data)))
        self.end_headers()
        self.wfile.write(zip_data)

    # ---- 共享剪切板 API ----

    def _api_clipboard_list(self):
        with clipboard_lock:
            entries = _load_clipboard()
        self._send_json({"items": list(reversed(entries))})

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
        body = self.rfile.read(content_length)
        delimiter = b"--" + boundary.encode()
        parts = body.split(delimiter)
        img_data = None
        mime = "image/png"
        for part in parts:
            if not part or part.strip() == b"--":
                continue
            if part.startswith(b"\r\n"):
                part = part[2:]
            if part.endswith(b"\r\n"):
                part = part[:-2]
            he = part.find(b"\r\n\r\n")
            if he == -1:
                continue
            hb = part[:he].decode("utf-8", errors="ignore")
            content = part[he + 4:]
            is_file = False
            for line in hb.split("\r\n"):
                if "filename=" in line:
                    m = re.search(r'filename="([^"]*)"', line)
                    if m and m.group(1):
                        is_file = True
                        mime = mimetypes.guess_type(m.group(1))[0] or "image/png"
            if is_file and content:
                img_data = content
                break
        if not img_data:
            self._send_json({"error": "未找到图片数据"}, 400)
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

    server = ThreadingHTTPServer((HOST, PORT), FileHandler)

    ip = get_local_ip()
    print("=" * 52)
    print("  HTTP 文件共享服务器已启动（网页版）")
    print("=" * 52)
    print(f"  本机 IP    : {ip}")
    print(f"  访问地址   : http://{ip}:{PORT}")
    print(f"  共享目录   : {SHARE_DIR}")
    print(f"  权限       : 上传 + 下载 + 删除")
    print("=" * 52)
    print("  局域网内其他设备用浏览器打开：")
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
