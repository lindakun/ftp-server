# -*- coding: utf-8 -*-
"""批量下载（zip 打包）功能测试。"""
import io
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import zipfile

BASE = "http://127.0.0.1:8089"


def wait_server():
    for i in range(15):
        try:
            with urllib.request.urlopen(BASE + "/api/list?path=", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("服务器未启动")


def api_post_json(path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def api_upload(filename, content, rel_dir=""):
    boundary = "----test_boundary_999"
    dir_part = ""
    if rel_dir:
        dir_part = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="dir"\r\n\r\n{rel_dir}\r\n'
        )
    body = (
        f"{dir_part}"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(BASE + "/api/upload", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def api_download_zip(paths):
    body = json.dumps({"paths": paths}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/download-zip", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def api_delete(path):
    api_post_json("/api/delete", {"path": path})


def main():
    print("等待服务器启动...")
    wait_server()
    print("[OK] 服务器已响应\n")

    # 准备：上传 3 个测试文件
    print("--- 准备：上传测试文件 ---")
    api_upload("a.txt", b"AAA content")
    api_upload("b.txt", b"BBB content")
    api_upload("c.txt", b"CCC content")
    print("[OK] 上传 a.txt, b.txt, c.txt")

    # 测试1：批量下载多个文件
    print("\n--- 测试1: 批量下载多个文件 ---")
    zip_data = api_download_zip(["a.txt", "b.txt", "c.txt"])
    zf = zipfile.ZipFile(io.BytesIO(zip_data))
    names = zf.namelist()
    print(f"[OK] 返回 zip，包含: {names}")
    assert set(names) == {"a.txt", "b.txt", "c.txt"}, f"文件列表不符: {names}"
    assert zf.read("a.txt") == b"AAA content"
    assert zf.read("b.txt") == b"BBB content"
    assert zf.read("c.txt") == b"CCC content"
    print("[OK] 3 个文件内容校验一致")

    # 测试2：批量下载部分文件
    print("\n--- 测试2: 批量下载部分文件 ---")
    zip_data = api_download_zip(["a.txt", "c.txt"])
    zf = zipfile.ZipFile(io.BytesIO(zip_data))
    names = zf.namelist()
    assert set(names) == {"a.txt", "c.txt"}, f"文件列表不符: {names}"
    print(f"[OK] 只下载了: {names}")

    # 测试3：批量下载含文件夹
    print("\n--- 测试3: 批量下载含文件夹 ---")
    api_upload("d.txt", b"DDD in subdir", rel_dir="testdir")
    zip_data = api_download_zip(["a.txt", "testdir"])
    zf = zipfile.ZipFile(io.BytesIO(zip_data))
    names = zf.namelist()
    print(f"[OK] 返回 zip，包含: {names}")
    assert "a.txt" in names
    assert any("testdir" in n and "d.txt" in n for n in names), "文件夹内文件未打包"
    assert zf.read("a.txt") == b"AAA content"
    print("[OK] 文件 + 文件夹混合打包正确")

    # 测试4：空选择报错
    print("\n--- 测试4: 空选择报错 ---")
    code, data = api_post_json("/api/download-zip", {"paths": []})
    assert code == 400, f"应返回400, 实际{code}"
    print(f"[OK] 空选择正确报错: {data.get('error')}")

    # 测试5：单个文件也能批量下载
    print("\n--- 测试5: 单个文件打包 ---")
    zip_data = api_download_zip(["b.txt"])
    zf = zipfile.ZipFile(io.BytesIO(zip_data))
    assert zf.namelist() == ["b.txt"]
    print("[OK] 单文件打包正常")

    # 清理
    print("\n--- 清理测试文件 ---")
    for p in ["a.txt", "b.txt", "c.txt"]:
        api_delete(p)
    api_delete("testdir")
    print("[OK] 清理完成")

    print("\n" + "=" * 48)
    print("  批量下载测试全部通过!")
    print("=" * 48)


if __name__ == "__main__":
    main()
