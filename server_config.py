"""读取不入 Git 的运行配置，环境变量优先。"""
import os
from pathlib import Path


def load_config():
    path = Path(os.environ.get("FILESHARE_CONFIG") or
                Path(__file__).with_name("server.env"))
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())
