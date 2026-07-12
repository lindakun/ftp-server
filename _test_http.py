# -*- coding: utf-8 -*-
"""HTTP 文件共享服务器功能自测。"""
import json
import os
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8089"
RETRIES = 15


def wait_server():
    for i in range(RETRIES):
        try:
            with urllib.request.urlopen(BASE + "/api/list?path=", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            if i == RETRIES - 1:
                raise
            time.sleep(0.5)


def api_get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def api_upload(filename, content):
    """构造 multipart 上传。"""
    boundary = "----test_boundary_12345"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="dir"\r\n\r\n\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(BASE + "/api/upload", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def api_download(path):
    with urllib.request.urlopen(BASE + "/api/download/" + urllib.parse.quote(path), timeout=5) as r:
        return r.read()


import urllib.parse


def main():
    print(f"等待 {BASE} 启动...")
    wait_server()
    print("[OK] 服务器已响应\n")

    # 1. 列目录（初始应为空或已有文件）
    print("--- 测试1: 列目录 ---")
    data = api_get("/api/list?path=")
    print(f"[OK] 当前文件数: {len(data['items'])}")

    # 2. 新建文件夹
    print("\n--- 测试2: 新建文件夹 ---")
    res = api_post_json("/api/mkdir", {"path": "", "name": "__test_dir"})
    assert res.get("ok"), f"新建失败: {res}"
    print("[OK] 创建 __test_dir 成功")

    # 3. 上传文件
    print("\n--- 测试3: 上传文件 ---")
    content = "达叔的HTTP文件服务测试~ 网页版OK!\n".encode("utf-8")
    res = api_upload("__test_http.txt", content)
    assert res["count"] == 1, f"上传失败: {res}"
    print(f"[OK] 上传 __test_http.txt 成功")

    # 4. 列目录确认
    print("\n--- 测试4: 确认文件存在 ---")
    data = api_get("/api/list?path=")
    names = [i["name"] for i in data["items"]]
    assert "__test_http.txt" in names, "上传的文件不在列表中"
    assert "__test_dir" in names, "新建的文件夹不在列表中"
    print(f"[OK] 文件列表: {names}")

    # 5. 下载并校验
    print("\n--- 测试5: 下载文件 ---")
    downloaded = api_download("__test_http.txt")
    assert downloaded == content, f"内容不一致! 下载={downloaded!r}"
    print(f"[OK] 下载成功，内容校验一致 ({len(downloaded)} 字节)")

    # 6. 重命名
    print("\n--- 测试6: 重命名 ---")
    res = api_post_json("/api/rename", {"path": "__test_http.txt", "name": "__test_renamed.txt"})
    assert res.get("ok"), f"重命名失败: {res}"
    data = api_get("/api/list?path=")
    names = [i["name"] for i in data["items"]]
    assert "__test_renamed.txt" in names, "重命名后文件不在列表中"
    print("[OK] 重命名为 __test_renamed.txt 成功")

    # 7. 删除文件
    print("\n--- 测试7: 删除文件 ---")
    res = api_post_json("/api/delete", {"path": "__test_renamed.txt"})
    assert res.get("ok"), f"删除失败: {res}"
    print("[OK] 删除文件成功")

    # 8. 删除文件夹
    print("\n--- 测试8: 删除文件夹 ---")
    res = api_post_json("/api/delete", {"path": "__test_dir"})
    assert res.get("ok"), f"删除失败: {res}"
    print("[OK] 删除文件夹成功")

    print("\n" + "=" * 48)
    print("  全部测试通过! HTTP 文件服务正常")
    print("=" * 48)


if __name__ == "__main__":
    main()
