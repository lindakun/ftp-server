"""拉取主服务的一致性剪切板备份，校验后发布，按份数保留。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

from server_config import load_config


def backup(url, token, output, keep):
    if not token or keep < 1:
        raise ValueError("必须配置备份密钥，保留份数必须大于零")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url.rstrip("/") + "/api/clipboard/backup",
                                     headers={"Authorization": "Bearer " + token})
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output, suffix=".tmp", delete=False) as target:
            temporary = Path(target.name)
            with urllib.request.urlopen(request, timeout=120) as response:
                shutil.copyfileobj(response, target, 64 * 1024)
                expected = response.headers.get("Content-Length")
                if expected is not None and target.tell() != int(expected):
                    raise ValueError("备份传输不完整")
            target.flush()
            os.fsync(target.fileno())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip():
                raise ValueError("备份文件校验失败")
            entries = json.loads(archive.read("clipboard.json"))
            if not isinstance(entries, list):
                raise ValueError("剪切板数据格式错误")
        name = "clipboard-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".zip"
        result = output / name
        os.replace(temporary, result)
        for old in sorted(output.glob("clipboard-[0-9]*.zip"), reverse=True)[keep:]:
            old.unlink()
        print(f"备份完成：{result}（{len(entries)} 条）")
        return result
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    load_config()
    host = os.environ.get('HTTP_HOST', '127.0.0.1')
    if host in ('0.0.0.0', '::'):
        host = '127.0.0.1'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("CLIPBOARD_PRIMARY_URL") or
                        f"http://{host}:{os.environ.get('HTTP_PORT', '8080')}")
    parser.add_argument("--output", required=True)
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    backup(args.url, os.environ.get("CLIPBOARD_BACKUP_TOKEN", ""), args.output, args.keep)


if __name__ == "__main__":
    main()
