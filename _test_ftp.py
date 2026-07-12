# -*- coding: utf-8 -*-
"""FTP 服务器功能自测：连接、列表、上传、下载、删除。"""
import io
import time
import ftplib

HOST = "127.0.0.1"
PORT = 21
RETRIES = 15


def wait_server():
    for i in range(RETRIES):
        try:
            ftp = ftplib.FTP()
            ftp.connect(HOST, PORT, timeout=3)
            ftp.login()  # 匿名
            return ftp
        except Exception as e:
            if i == RETRIES - 1:
                raise
            time.sleep(0.5)
    raise RuntimeError("无法连接服务器")


def main():
    print(f"正在连接 ftp://{HOST}:{PORT} ...")
    ftp = wait_server()
    print(f"[OK] 连接成功，欢迎语: {ftp.getwelcome()}")

    # 1. 列目录
    print("\n--- 测试1: 列目录 ---")
    files = ftp.nlst()
    print(f"[OK] 当前文件列表: {files}")

    # 2. 上传文件
    print("\n--- 测试2: 上传文件 ---")
    content = "这是达叔的FTP测试文件~ 局域网共享OK!\n".encode("utf-8")
    ftp.storbinary("STOR __test_upload.txt", io.BytesIO(content))
    print("[OK] 上传 __test_upload.txt 成功")

    # 3. 下载并校验
    print("\n--- 测试3: 下载文件 ---")
    buf = io.BytesIO()
    ftp.retrbinary("RETR __test_upload.txt", buf.write)
    downloaded = buf.getvalue()
    assert downloaded == content, f"内容不一致! 下载={downloaded!r}"
    print(f"[OK] 下载成功，内容校验一致 ({len(downloaded)} 字节)")

    # 4. 再次列目录确认
    print("\n--- 测试4: 确认文件存在 ---")
    files = ftp.nlst()
    assert "__test_upload.txt" in files, "文件不在列表中"
    print(f"[OK] 文件列表: {files}")

    # 5. 删除测试文件
    print("\n--- 测试5: 删除文件 ---")
    ftp.delete("__test_upload.txt")
    files = ftp.nlst()
    assert "__test_upload.txt" not in files, "文件删除失败"
    print("[OK] 删除成功")

    # 6. 创建目录测试
    print("\n--- 测试6: 创建目录 ---")
    ftp.mkd("__test_dir")
    ftp.rmd("__test_dir")
    print("[OK] 创建/删除目录成功")

    ftp.quit()
    print("\n" + "=" * 48)
    print("  全部测试通过! FTP 服务器运行正常")
    print("=" * 48)


if __name__ == "__main__":
    main()
