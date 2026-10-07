"""安装 NAS 主服务或 Windows 剪切板入口；只生成运行配置和服务定义。"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["primary", "gateway"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--user")
    parser.add_argument("--primary-url")
    args = parser.parse_args()
    token = os.environ.get("CLIPBOARD_BACKUP_TOKEN", "")
    if not token:
        parser.error("请通过环境变量传入 CLIPBOARD_BACKUP_TOKEN")
    config = BASE / "server.env"
    if config.exists():
        parser.error("server.env 已存在，请先保留旧配置再重新安装")
    if args.role == "primary":
        if os.name == "nt" or os.geteuid() != 0 or not args.data_root or not args.user:
            parser.error("主服务安装需要 Linux root 权限、--data-root 和 --user")
        import pwd
        account = pwd.getpwnam(args.user)
        for path in (args.data_root, args.data_root / "data", args.data_root / "shared",
                     args.data_root / "backups"):
            path.mkdir(parents=True, exist_ok=True)
            os.chown(path, account.pw_uid, account.pw_gid)
            path.chmod(0o700)
        values = {"HTTP_HOST": args.host, "HTTP_PORT": str(args.port),
                  "SHARE_DIR": str(args.data_root / "shared"),
                  "DATA_DIR": str(args.data_root / "data"), "TZ": "Asia/Shanghai"}
    else:
        if os.name != "nt" or not args.primary_url:
            parser.error("入口安装需要 Windows 和 --primary-url")
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            parser.error("入口安装需要管理员权限")
        values = {"HTTP_HOST": args.host, "HTTP_PORT": str(args.port),
                  "CLIPBOARD_PRIMARY_URL": args.primary_url.rstrip("/")}
    values["CLIPBOARD_BACKUP_TOKEN"] = token
    config.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    if args.role == "primary":
        os.chown(config, account.pw_uid, account.pw_gid)
        config.chmod(0o600)
        replacements = {"@APP_DIR@": str(BASE), "@DATA_ROOT@": str(args.data_root),
                        "@USER@": args.user}
        for template in (BASE / "deploy" / "lan").iterdir():
            text = template.read_text(encoding="utf-8")
            for old, new in replacements.items():
                text = text.replace(old, new)
            (Path("/etc/systemd/system") / template.name).write_text(text, encoding="utf-8")
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", "fileshare-lan.service",
                        "fileshare-lan-backup.timer"], check=True)
    else:
        # 配置含备份密钥，只允许管理员和 SYSTEM 读取。
        subprocess.run(["icacls", str(config), "/inheritance:r", "/grant:r",
                        "*S-1-5-18:F", "*S-1-5-32-544:F"], check=True, stdout=subprocess.DEVNULL)
        from install_service import gen_xml, install
        if not install("web"):
            raise RuntimeError("入口任务安装失败")
        python = str(BASE / ".venv" / "Scripts" / "python.exe")
        arguments = f'clipboard_backup.py --output "{BASE / "data" / "backups"}" --keep 24'
        xml = gen_xml("FileShareClipboardBackup", "共享剪切板备份", python, arguments, str(BASE))
        # 启动时备份，之后每小时备份；NAS 不可达时保留已有备份。
        xml = xml.replace("<Enabled>true</Enabled>\n    </BootTrigger>",
                          "<Enabled>true</Enabled><Repetition><Interval>PT1H</Interval>"
                          "<StopAtDurationEnd>false</StopAtDurationEnd></Repetition>\n    </BootTrigger>")
        xml = xml.replace("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>",
                          "<ExecutionTimeLimit>PT30M</ExecutionTimeLimit>")
        # XML 参数中的路径引号需转义。
        from xml.sax.saxutils import escape
        xml = xml.replace(f"<Arguments>{arguments}</Arguments>",
                          f"<Arguments>{escape(arguments)}</Arguments>")
        task = BASE / "_clipboard_backup_task.xml"
        try:
            task.write_text(xml, encoding="utf-16")
            subprocess.run(["schtasks", "/create", "/tn", "FileShareClipboardBackup",
                            "/xml", str(task), "/f"], check=True)
        finally:
            task.unlink(missing_ok=True)
    print(f"安装完成：{args.role}，端口 {args.port}")


if __name__ == "__main__":
    main()
