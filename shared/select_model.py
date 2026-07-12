#!/usr/bin/env python3
"""由 start.sh 调用的模型选择器 —— 用 longcat 分析命令复杂度，返回 turbo 或 lite"""
import sys, json, urllib.request
from pathlib import Path


def extract_longcat_config(yaml_path: str):
    """从 YAML 配置中提取 longcat 的 api_key 和 api_base"""
    lines = Path(yaml_path).read_text(encoding="utf-8").splitlines()
    api_key, api_base = "", ""
    in_longcat = False
    longcat_indent = -1  # longcat 段的缩进级别
    for line in lines:
        if not in_longcat:
            if line.strip() == "longcat: &longcat":
                in_longcat = True
                longcat_indent = len(line) - len(line.lstrip())
            continue
        # 在 longcat 段中
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        # 缩进小于等于 longcat 缩进 → 退出段
        if indent <= longcat_indent:
            break
        if stripped.startswith("api_base:"):
            api_base = stripped.split("api_base:", 1)[1].strip()
        elif stripped.startswith("api_key:"):
            api_key = stripped.split("api_key:", 1)[1].strip().strip("'\"")
    return api_key, api_base


def classify_complexity(cmd: str) -> str:
    """用 longcat 判断任务复杂度，返回 'turbo' 或 'lite'"""
    prompt = (
        "你是一个移动端自动化任务复杂度分析助手。\n"
        "分析下面这条命令，只需返回一个词：turbo 或 lite。\n\n"
        "返回 turbo（强视觉模型，更精准但慢）：\n"
        '- 需要区分列表中特定项，如"第N新"、"第N个"、"最新"、"最旧"\n'
        "- 需要对比/筛选/找出特定内容\n"
        "- 需要在复杂页面中精确点击特定区域\n\n"
        "返回 lite（轻量模型，快速但视觉精度一般）：\n"
        "- 简单导航操作：打开应用、搜索、点击首页内容\n"
        "- 基础互动：点赞、评论、关注、收藏\n"
        "- 不需要在列表中精确定位到特定条目\n\n"
        f"命令：{cmd}\n\n"
        "只返回 turbo 或 lite，不要其他内容。"
    )

    payload = json.dumps({
        "model": "LongCat-2.0",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.0,
    }).encode()

    req = urllib.request.Request(
        api_base.rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        msg = result["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning_content") or ""
        choice = content.strip().lower()
        if "turbo" in choice:
            return "turbo"
        elif "lite" in choice:
            return "lite"
        else:
            print(f"longcat 返回无法解析：「{content}」，默认用 turbo", file=sys.stderr)
            return "turbo"
    except Exception as e:
        print(f"longcat 调用失败：{e}，默认用 turbo", file=sys.stderr)
        return "turbo"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：select_model.py <yaml_path> <command>", file=sys.stderr)
        print("turbo", file=sys.stdout)
        sys.exit(1)

    yaml_path = sys.argv[1]
    command = sys.argv[2]

    api_key, api_base = extract_longcat_config(yaml_path)
    if not api_key or not api_base:
        print("无法读取 longcat 配置，默认用 turbo", file=sys.stderr)
        print("turbo")
        sys.exit(0)

    result = classify_complexity(command)
    print(result)
