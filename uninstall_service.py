# -*- coding: utf-8 -*-
"""
卸载开机自启服务。需管理员权限运行，双击 uninstall_service.bat 即可。

用法：
    python uninstall_service.py          # 卸载全部
    python uninstall_service.py web      # 只卸载网页版
    python uninstall_service.py ftp      # 只卸载 FTP 版
    python uninstall_service.py all      # 卸载全部
"""

import ctypes
import subprocess
import sys

SERVICES = {
    "web": "FileShareWeb",
    "ftp": "FileShareFTP",
}


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def main():
    if not is_admin():
        print("[错误] 需要管理员权限！请右键 uninstall_service.bat 以管理员身份运行")
        sys.exit(1)

    targets = sys.argv[1:] if len(sys.argv) > 1 else ["all"]
    if "all" in targets:
        targets = list(SERVICES.keys())

    print("=" * 52)
    print("  卸载开机自启服务")
    print("=" * 52)
    print()

    for key in targets:
        task_name = SERVICES.get(key)
        if not task_name:
            continue
        # 先停止运行中的任务
        subprocess.run(["schtasks", "/end", "/tn", task_name], capture_output=True)
        # 删除任务
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True,
        )
        if result.returncode == 0:
            print(f"  [OK] 已卸载 {task_name}")
        else:
            print(f"  [跳过] {task_name} 不存在或已卸载")

    print()
    print("卸载完成。服务已停止并取消开机自启。")
    print("如需重新安装，双击 install_service.bat 即可。")


if __name__ == "__main__":
    main()
