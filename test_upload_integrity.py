"""验证上传完整性、故障清理和资源保护，不写入实际共享目录。"""
import errno
import http.client
import io
import os
import socket
import tempfile
import threading
import time
import unittest
from collections import namedtuple
from unittest.mock import patch

import http_server as server


def multipart(files, closing=True):
    body = b""
    for name, data in files:
        body += (f'--probe\r\nContent-Disposition: form-data; name="files"; '
                 f'filename="{name}"\r\n\r\n').encode() + data + b"\r\n"
    return body + (b"--probe--\r\n" if closing else b"")


class UploadIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.shared = os.path.join(self.root.name, "shared")
        self.spool = os.path.join(self.root.name, "spool")
        os.mkdir(self.shared)
        os.mkdir(self.spool)
        for name, value in (("SHARE_DIR", self.shared), ("SPOOL_DIR", self.spool),
                            ("upload_slots", threading.BoundedSemaphore(2))):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.handler = object.__new__(server.FileHandler)
        self.replies = []
        self.handler._send_json = lambda data, code=200: self.replies.append((code, data))

    def upload(self, body, declared_length=None, reader=None):
        self.handler.headers = {
            "Content-Type": "multipart/form-data; boundary=probe",
            "Content-Length": str(len(body) if declared_length is None else declared_length),
        }
        self.handler.rfile = reader if reader is not None else io.BytesIO(body)
        self.handler._api_upload()
        self.assertEqual(os.listdir(self.spool), [])
        return self.replies[-1]

    def test_complete_files(self):
        files = [(f"file{i}.bin", bytes([i]) * 1000) for i in range(16)]
        code, data = self.upload(multipart(files))
        self.assertEqual((code, data["count"]), (200, 16))
        for name, expected in files:
            with open(os.path.join(self.shared, name), "rb") as saved:
                self.assertEqual(saved.read(), expected)

    def test_early_eof_preserves_existing_file(self):
        target = os.path.join(self.shared, "file.bin")
        with open(target, "wb") as saved:
            saved.write(b"original")
        body = multipart([("file.bin", b"x" * 200000)], closing=False)
        code, _ = self.upload(body, len(body) + 1000000)
        self.assertEqual(code, 400)
        with open(target, "rb") as saved:
            self.assertEqual(saved.read(), b"original")

    def test_missing_boundary_with_exact_length(self):
        code, _ = self.upload(multipart([("bad.bin", b"x" * 200000)], closing=False))
        self.assertEqual(code, 400)
        self.assertEqual(os.listdir(self.shared), [])

    def test_truncated_end_marker(self):
        for suffix in (b"", b"-", b"--\r", b"broken"):
            with self.subTest(suffix=suffix):
                body = multipart([("bad.bin", b"data")])[:-4] + suffix
                code, _ = self.upload(body)
                self.assertEqual(code, 400)
                self.assertEqual(os.listdir(self.shared), [])

    def test_declared_length_not_fully_received(self):
        body = multipart([("bad.bin", b"data")])
        code, _ = self.upload(body, len(body) + 10)
        self.assertEqual(code, 400)
        self.assertEqual(os.listdir(self.shared), [])

    def test_limit_in_final_buffer_and_following_file(self):
        with patch.object(server, "MAX_UPLOAD_BYTES", 10):
            code, data = self.upload(multipart([("big.bin", b"x" * 11), ("ok.bin", b"ok")]))
        self.assertEqual(code, 200)
        self.assertEqual(data["oversize"], ["big.bin"])
        self.assertEqual(data["uploaded"], ["ok.bin"])
        self.assertFalse(os.path.exists(os.path.join(self.shared, "big.bin")))

    def test_limit_across_buffers(self):
        with patch.object(server, "MAX_UPLOAD_BYTES", 100000):
            code, _ = self.upload(multipart([("big.bin", b"x" * 200000)]))
        self.assertEqual(code, 413)
        self.assertEqual(os.listdir(self.shared), [])

    def test_timeout_after_temporary_file_creation(self):
        body = multipart([("bad.bin", b"x" * 200000)])
        stream = io.BytesIO(body)

        class TimedOut:
            def read(self, size):
                if stream.tell():
                    raise socket.timeout()
                return stream.read(size)

        code, _ = self.upload(body, reader=TimedOut())
        self.assertEqual(code, 408)
        self.assertEqual(os.listdir(self.shared), [])

    def test_disk_write_error(self):
        fdopen = os.fdopen

        class FullDisk:
            def __init__(self, fd):
                self.file = fdopen(fd, "wb")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.file.close()
            def write(self, data):
                raise OSError(errno.ENOSPC, "磁盘已满")

        with patch.object(server.os, "fdopen", side_effect=lambda fd, mode: FullDisk(fd)):
            code, _ = self.upload(multipart([("bad.bin", b"data")]))
        self.assertEqual(code, 500)
        self.assertEqual(os.listdir(self.shared), [])

    def test_disk_space_precheck(self):
        usage = namedtuple("Usage", "total used free")(1000, 999, 1)
        with patch.object(server.shutil, "disk_usage", return_value=usage):
            code, _ = self.upload(multipart([("bad.bin", b"data")]))
        self.assertEqual(code, 507)
        self.assertEqual(os.listdir(self.shared), [])

    def test_cross_disk_copy_failure_preserves_original(self):
        target = os.path.join(self.shared, "file.bin")
        with open(target, "wb") as saved:
            saved.write(b"original")
        replace = os.replace

        def cross_disk(source, destination):
            if os.path.dirname(source) == self.spool:
                raise OSError(errno.EXDEV, "跨盘")
            return replace(source, destination)

        def failed_copy(source, destination):
            with open(destination, "wb") as partial:
                partial.write(b"partial")
            raise OSError(errno.ENOSPC, "目标盘已满")

        with patch.object(server.os, "replace", side_effect=cross_disk), \
             patch.object(server.shutil, "copyfile", side_effect=failed_copy):
            code, _ = self.upload(multipart([("file.bin", b"new data")]))
        self.assertEqual(code, 500)
        self.assertEqual(os.listdir(self.shared), ["file.bin"])
        with open(target, "rb") as saved:
            self.assertEqual(saved.read(), b"original")

    def test_busy_and_released_after_failure(self):
        server.upload_slots.acquire()
        server.upload_slots.acquire()
        try:
            code, _ = self.upload(multipart([("file.bin", b"data")]))
            self.assertEqual(code, 503)
        finally:
            server.upload_slots.release()
            server.upload_slots.release()
        code, _ = self.upload(b"bad")
        self.assertEqual(code, 400)
        code, data = self.upload(multipart([("file.bin", b"data")]))
        self.assertEqual((code, data["count"]), (200, 1))

    def test_boundary_split_across_every_byte(self):
        body = multipart([("file.bin", b"data")])

        class Fragmented(io.BytesIO):
            def read(self, size):
                return super().read(min(size, 1))

        code, data = self.upload(body, reader=Fragmented(body))
        self.assertEqual((code, data["count"]), (200, 1))

    def live_server(self):
        class Handler(server.FileHandler):
            timeout = 0.5
            def log_message(self, *args):
                pass

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd.server_address

    def test_real_connection_early_eof(self):
        address = self.live_server()
        body = multipart([("bad.bin", b"x" * 200000)], closing=False)
        with socket.create_connection(address, timeout=3) as connection:
            headers = (f"POST /api/upload HTTP/1.1\r\nHost: localhost\r\n"
                       f"Content-Type: multipart/form-data; boundary=probe\r\n"
                       f"Content-Length: {len(body) + 1000000}\r\n\r\n").encode()
            connection.sendall(headers + body)
            connection.shutdown(socket.SHUT_WR)
            response = http.client.HTTPResponse(connection)
            response.begin()
            self.assertEqual(response.status, 400)
            response.read()
        self.assertEqual(os.listdir(self.shared), [])
        self.assertEqual(os.listdir(self.spool), [])

    def test_real_connection_idle_timeout_and_slow_success(self):
        address = self.live_server()
        body = multipart([("ok.bin", b"x" * 300000)])
        connection = http.client.HTTPConnection(*address, timeout=3)
        self.addCleanup(connection.close)
        connection.putrequest("POST", "/api/upload")
        connection.putheader("Content-Type", "multipart/form-data; boundary=probe")
        connection.putheader("Content-Length", str(len(body)))
        connection.endheaders()
        connection.send(body[:100])
        response = connection.getresponse()
        self.assertEqual(response.status, 408)
        response.read()
        self.assertEqual(os.listdir(self.spool), [])
        self.assertEqual(os.listdir(self.shared), [])
        connection.close()
        connection.connect()
        connection.putrequest("POST", "/api/upload")
        connection.putheader("Content-Type", "multipart/form-data; boundary=probe")
        connection.putheader("Content-Length", str(len(body)))
        connection.endheaders()
        # 总时长超过读取超时，持续收到数据仍应成功。
        for offset in range(0, len(body), 65536):
            connection.send(body[offset:offset + 65536])
            time.sleep(0.15)
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        self.assertEqual(os.path.getsize(os.path.join(self.shared, "ok.bin")), 300000)


if __name__ == "__main__":
    unittest.main()
