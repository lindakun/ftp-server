"""验证上传文件在发布前就可被曲库读取。"""
import errno
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import http_server


@unittest.skipIf(os.name == "nt", "Windows 没有 POSIX 读取权限")
class UploadPermissionsTest(unittest.TestCase):
    def test_permissions_before_publish(self):
        for cross_device in (False, True):
            for name in ("单曲.mp3", "专辑/歌曲.mp3"):
                with self.subTest(cross_device=cross_device, name=name):
                    with tempfile.TemporaryDirectory() as root:
                        shared = os.path.join(root, "shared")
                        os.mkdir(shared)
                        fd, temporary = tempfile.mkstemp(dir=root)
                        with os.fdopen(fd, "wb") as output:
                            output.write(b"audio bytes")
                        self.assertEqual(stat.S_IMODE(os.stat(temporary).st_mode), 0o600)
                        replace = os.replace

                        def publish(source, destination):
                            self.assertEqual(stat.S_IMODE(os.stat(source).st_mode), 0o644)
                            if cross_device:
                                raise OSError(errno.EXDEV, "跨文件系统")
                            return replace(source, destination)

                        handler = object.__new__(http_server.FileHandler)
                        with patch.object(http_server, "SHARE_DIR", shared), \
                             patch.object(http_server.os, "replace", side_effect=publish), \
                             patch.object(http_server.os, "rename", side_effect=OSError(errno.EXDEV, "跨文件系统")):
                            result = handler._save_upload(temporary, name, "音乐")
                        saved = os.path.join(shared, result)
                        self.assertEqual(stat.S_IMODE(os.stat(saved).st_mode), 0o644)
                        with open(saved, "rb") as audio:
                            self.assertEqual(audio.read(), b"audio bytes")
                        self.assertFalse(os.path.exists(temporary))


if __name__ == "__main__":
    unittest.main()
