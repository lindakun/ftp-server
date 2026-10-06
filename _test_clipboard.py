# -*- coding: utf-8 -*-
"""共享剪切板功能自测。"""
import io
import json
import urllib.request
import urllib.error
import urllib.parse

BASE = "http://127.0.0.1:8089"
passed = 0
failed = 0


def call(method, path, data=None, raw=None, ctype="application/json"):
    url = BASE + path
    if raw is not None:
        body = raw
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
    else:
        body = None
    headers = {}
    if body is not None:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  {extra}")


print("=== 1. 清空初始状态 ===")
st, _ = call("POST", "/api/clipboard/clear")
check("清空成功", st == 200)

print("=== 2. 发布文字 ===")
st, body = call("POST", "/api/clipboard", {"text": "你好，这是共享剪切板测试 🌸\n第二行内容 http://example.com"})
check("发布返回 200", st == 200)
entry = json.loads(body).get("entry", {})
tid = entry.get("id")
check("返回条目 id", bool(tid))
check("内容为文字类型", entry.get("type") == "text")

print("=== 3. 列表应含刚发布的文字 ===")
st, body = call("GET", "/api/clipboard")
items = json.loads(body).get("items", [])
check("列表 200", st == 200)
check("列表非空", len(items) >= 1)
check("最新在前", items and items[0]["id"] == tid)

print("=== 4. 空内容应被拒绝 ===")
st, _ = call("POST", "/api/clipboard", {"text": "   "})
check("空内容返回 400", st == 400)

print("=== 5. 发布图片（1x1 PNG）===")
png = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489000000"
    "0d49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)
st, body = call("POST", "/api/clipboard/image", raw=png,
                ctype="multipart/form-data; boundary=----t")
# 上面直接用裸 png 不是合法 multipart，改用正确 multipart 封装
boundary = "----clipbtest"
payload = (
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="file"; filename="a.png"\r\n'
    "Content-Type: image/png\r\n\r\n"
).encode() + png + f"\r\n--{boundary}--\r\n".encode()
st, body = call("POST", "/api/clipboard/image", raw=payload,
                ctype=f"multipart/form-data; boundary={boundary}")
check("图片发布 200", st == 200, body)
img_entry = json.loads(body).get("entry", {})
iid = img_entry.get("id")
check("图片条目有 id", bool(iid))
check("图片类型为 image", img_entry.get("type") == "image")

print("=== 6. 图片可访问 ===")
try:
    with urllib.request.urlopen(BASE + "/api/clipboard/file/" + iid, timeout=10) as r:
        img_data = r.read()
    check("图片 GET 200 且内容一致", r.status == 200 and img_data == png)
except Exception as e:
    check("图片 GET 200 且内容一致", False, str(e))

print("=== 7. 列表应含 2 条（文字+图片）===")
st, body = call("GET", "/api/clipboard")
items = json.loads(body).get("items", [])
check("共 2 条", len(items) == 2, f"实际 {len(items)}")

print("=== 7. 编辑文字条目 ===")
st, body = call("POST", "/api/clipboard/edit", {"id": tid, "text": "你好，这是编辑后的内容 v2 http://example.com/edited"})
check("编辑返回 200", st == 200, body)
edited = json.loads(body).get("entry", {})
check("编辑后内容正确", "编辑后的内容 v2" in edited.get("text", ""))
check("带 updated_at 标记", bool(edited.get("updated_at")))

st, body = call("GET", "/api/clipboard")
items = json.loads(body).get("items", [])
edited_item = next((e for e in items if e.get("id") == tid), None)
check("列表反映编辑结果", edited_item is not None and "编辑后的内容 v2" in edited_item.get("text", ""))
check("编辑后带 updated_at", bool(edited_item and edited_item.get("updated_at")))
check("编辑不改条数", len(items) == 2, f"实际 {len(items)}")

print("=== 7.1 编辑校验 ===")
st, _ = call("POST", "/api/clipboard/edit", {"id": tid, "text": "   "})
check("编辑空内容返回 400", st == 400)
st, _ = call("POST", "/api/clipboard/edit", {"id": "no-such-id", "text": "内容"})
check("编辑不存在条目返回 404", st == 404)
st, _ = call("POST", "/api/clipboard/edit", {"id": iid, "text": "给图片改文字"})
check("编辑图片条目返回 400", st == 400)

print("=== 7.2 服务端搜索 ===")
st, body = call("GET", "/api/clipboard?q=" + urllib.parse.quote("编辑后"))
items = json.loads(body).get("items", [])
check("搜索命中文字条目", st == 200 and len(items) == 1 and items[0]["id"] == tid)
st, body = call("GET", "/api/clipboard?q=" + urllib.parse.quote("绝对不存在的关键词xyz"))
items = json.loads(body).get("items", [])
check("搜索无结果返回空", st == 200 and len(items) == 0)
st, body = call("GET", "/api/clipboard")
items = json.loads(body).get("items", [])
check("不带 q 返回全部（含图片）", st == 200 and len(items) == 2)

print("=== 8. 删除文字条目 ===")
st, _ = call("DELETE", "/api/clipboard/" + tid)
check("删除 200", st == 200)
st, body = call("GET", "/api/clipboard")
items = json.loads(body).get("items", [])
check("删除后剩 1 条", len(items) == 1, f"实际 {len(items)}")

print("=== 9. 清空全部 ===")
st, _ = call("POST", "/api/clipboard/clear")
check("清空 200", st == 200)
st, body = call("GET", "/api/clipboard")
items = json.loads(body).get("items", [])
check("清空后为空", len(items) == 0, f"实际 {len(items)}")

print(f"\n=== 结果: 通过 {passed} / 失败 {failed} ===")
import sys
sys.exit(1 if failed else 0)
