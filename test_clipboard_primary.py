"""用两个真实 HTTP 进程验证主服务、入口转发和一致性备份。"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile
import io

from clipboard_backup import backup


class ClipboardPrimaryTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.token = "test-only-backup-token"
        self.primary = self.start("primary")
        self.gateway = self.start("gateway", self.primary)

    def start(self, name, upstream=""):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        root = Path(self.root.name) / name
        env = dict(os.environ, HTTP_HOST="127.0.0.1", HTTP_PORT=str(port),
                   SHARE_DIR=str(root / "shared"), DATA_DIR=str(root / "data"),
                   FILESHARE_CONFIG=str(root / "missing.env"),
                   CLIPBOARD_PRIMARY_URL=upstream, CLIPBOARD_BACKUP_TOKEN=self.token)
        process = subprocess.Popen([sys.executable, "http_server.py"], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        self.addCleanup(stop)
        if name == "primary":
            self.primary_process = process
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with urllib.request.urlopen(url, timeout=1):
                    return url
            except urllib.error.URLError:
                if process.poll() is not None:
                    self.fail("服务未能启动")
                time.sleep(0.05)
        self.fail("服务启动超时")

    def call(self, url, path="/api/clipboard", method="GET", data=None, headers=None):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers = dict(headers or {}, **{"Content-Type": "application/json"})
        request = urllib.request.Request(url + path, data=data, method=method, headers=headers or {})
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, response.read()

    def add(self, url, text):
        status, body = self.call(url, method="POST", data={"text": text})
        self.assertEqual(status, 200)
        return json.loads(body)["entry"]["id"]

    def test_text_edit_search_delete_and_clear_share_one_store(self):
        cid = self.add(self.gateway, "入口发布")
        self.add(self.primary, "主服务发布")
        self.assertEqual(self.call(self.gateway), self.call(self.primary))
        self.assertEqual(self.call(self.gateway, "/api/clipboard/edit", "POST",
                                   {"id": cid, "text": "更新后的文字"})[0], 200)
        status, body = self.call(self.gateway, "/api/clipboard?q=" + urllib.parse.quote("更新后"))
        self.assertEqual(len(json.loads(body)["items"]), 1)
        self.assertEqual(self.call(self.primary, "/api/clipboard/" + cid, "DELETE")[0], 200)
        self.assertEqual(self.call(self.gateway, "/api/clipboard/" + cid, "DELETE")[0], 404)
        self.assertEqual(self.call(self.gateway, "/api/clipboard/clear", "POST")[0], 200)
        self.assertEqual(json.loads(self.call(self.primary)[1])["items"], [])
        self.assertFalse((Path(self.root.name) / "gateway/data/clipboard.json").exists())

    def test_images_and_authenticated_backup(self):
        image = b"\x89PNG\r\n\x1a\n" + b"test image bytes"
        body = (b'--probe\r\nContent-Disposition: form-data; name="image"; filename="test.png"\r\n'
                b'Content-Type: image/png\r\n\r\n' + image + b'\r\n--probe--\r\n')
        status, reply = self.call(self.gateway, "/api/clipboard/image", "POST", body,
                                  {"Content-Type": "multipart/form-data; boundary=probe"})
        self.assertEqual(status, 200)
        cid = json.loads(reply)["entry"]["id"]
        self.assertEqual(self.call(self.gateway, "/api/clipboard/file/" + cid), (200, image))
        self.assertEqual(self.call(self.primary, "/api/clipboard/backup")[0], 403)
        headers = {"Authorization": "Bearer " + self.token}
        self.assertEqual(self.call(self.gateway, "/api/clipboard/backup", headers=headers)[0], 403)
        status, snapshot = self.call(self.primary, "/api/clipboard/backup", headers=headers)
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("clipboard_files/" + cid + ".png"), image)
            self.assertEqual(json.loads(archive.read("clipboard.json"))[0]["id"], cid)
        output = Path(self.root.name) / "backups"
        for _ in range(3):
            backup(self.primary, self.token, output, 2)
        self.assertEqual(len(list(output.glob("*.zip"))), 2)
        with self.assertRaises(urllib.error.HTTPError):
            backup(self.primary, "wrong-token", output, 2)
        self.assertEqual(len(list(output.glob("*.zip"))), 2)
        self.assertEqual(list(output.glob("*.tmp")), [])

    def test_primary_offline_never_writes_gateway_and_files_still_work(self):
        self.primary_process.terminate()
        self.primary_process.wait(timeout=5)
        self.assertEqual(self.call(self.gateway, method="POST", data={"text": "不能落到入口"})[0], 503)
        self.assertFalse((Path(self.root.name) / "gateway/data/clipboard.json").exists())
        self.assertEqual(self.call(self.gateway, "/api/list")[0], 200)
        self.assertEqual(self.call(self.gateway, "/api/mkdir", "POST", {"path": "", "name": "local"})[0], 200)
        self.assertTrue((Path(self.root.name) / "gateway/shared/local").is_dir())


if __name__ == "__main__":
    unittest.main()
