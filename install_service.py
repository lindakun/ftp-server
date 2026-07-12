# -*- coding: utf-8 -*-
"""
安装开机自启服务（Windows 任务计划程序）。
需管理员权限运行，双击 install_service.bat 即可。

用法：
    python install_service.py          # 安装网页版（默认）
    python install_service.py web      # 安装网页版
    python install_service.py ftp      # 安装 FTP 版
    python install_service.py all      # 安装全部
"""

import ctypes
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHONW = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")

SERVICES = {
    "web": {
        "task_name": "FileShareWeb",
        "script": "http_server.py",
        "desc": "局域网文件共享-网页版(8080)",
        "port": 8080,
    },
    "ftp": {
        "task_name": "FileShareFTP",
        "script": "ftp_server.py",
        "desc": "局域网文件共享-FTP版(21)",
        "port": 21,
    },
}


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def gen_xml(task_name, desc, pythonw, script, work_dir):
    """生成任务计划 XML 配置。"""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{desc}</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>{script}</Arguments>
      <WorkingDirectory>{work_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""


def install(key):
    """安装单个服务。"""
    svc = SERVICES[key]
    if not os.path.isfile(PYTHONW):
        print(f"  [错误] 找不到 pythonw.exe: {PYTHONW}")
        return False

    xml = gen_xml(svc["task_name"], svc["desc"], PYTHONW, svc["script"], BASE_DIR)
    xml_path = os.path.join(BASE_DIR, f"_{key}_task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml)

    try:
        subprocess.run(
            ["schtasks", "/create", "/tn", svc["task_name"], "/xml", xml_path, "/f"],
            check=True, capture_output=True,
        )
        print(f"  [OK] {svc['desc']} 已安装")
        print(f"       任务名: {svc['task_name']}  端口: {svc['port']}")
        return True
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("gbk", errors="ignore") if e.stderr else str(e)
        print(f"  [错误] 安装失败: {err}")
        return False
    finally:
        if os.path.isfile(xml_path):
            os.remove(xml_path)


def start(key):
    """立即启动服务。"""
    svc = SERVICES[key]
    subprocess.run(["schtasks", "/run", "/tn", svc["task_name"]], capture_output=True)
    print(f"  [OK] 已启动 {svc['task_name']}")


def main():
    if not is_admin():
        print("[错误] 需要管理员权限！请右键 install_service.bat 以管理员身份运行")
        sys.exit(1)

    targets = sys.argv[1:] if len(sys.argv) > 1 else ["web"]
    if "all" in targets:
        targets = list(SERVICES.keys())

    print("=" * 52)
    print("  安装开机自启服务（任务计划程序）")
    print("=" * 52)
    print()

    success = []
    for key in targets:
        if key not in SERVICES:
            print(f"  [跳过] 未知服务: {key}")
            continue
        if install(key):
            success.append(key)
        print()

    if not success:
        print("没有成功安装任何服务。")
        return

    print(f"共安装 {len(success)} 个服务，正在立即启动...")
    for key in success:
        start(key)

    print()
    print("=" * 52)
    print("  安装完成！")
    print("=" * 52)
    print()
    print("  服务特性：")
    print("    - 开机自动启动（无需用户登录）")
    print("    - 后台运行（无窗口，用 pythonw.exe）")
    print("    - 崩溃自动重启（间隔1分钟）")
    print("    - 日志文件: logs/server.log")
    print()
    print("  管理命令（管理员CMD）：")
    for key in success:
        svc = SERVICES[key]
        print(f"    启动: schtasks /run /tn {svc['task_name']}")
        print(f"    停止: schtasks /end /tn {svc['task_name']}")
        print(f"    状态: schtasks /query /tn {svc['task_name']} /v")
    print(f"    卸载: 运行 uninstall_service.bat")
    print()
    print("  取消开机自启，双击 uninstall_service.bat 即可。")


if __name__ == "__main__":
    main()
