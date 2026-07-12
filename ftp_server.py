# -*- coding: utf-8 -*-
"""
局域网 FTP 共享服务器
基于 pyftpdlib，匿名访问，支持上传下载。

启动方式：
    python ftp_server.py
或双击 start.bat
按 Ctrl+C 停止。
"""

import os
import socket
import sys

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

# ===== 配置区（可按需修改）=====

# 共享文件根目录（脚本同级 shared 文件夹）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARE_DIR = os.path.join(BASE_DIR, "shared")

# 监听地址与端口（0.0.0.0 表示所有网卡）
HOST = "0.0.0.0"
PORT = 21

# 匿名用户权限（完整读写）
# e=改目录 l=列目录 r=读/下载 a=追加 d=删 f=改名 m=建目录 w=上传 M=改权限 T=改时间
ANON_PERM = "elradfmwMT"

# 被动模式端口范围（FTP 数据传输用）
PASV_PORT_START = 60000
PASV_PORT_END = 60100

# 最大连接数 / 单 IP 最大连接
MAX_CONS = 50
MAX_CONS_PER_IP = 5

# 欢迎语
BANNER = "欢迎来到达叔的 FTP 共享服务器~"

# ==============================


def get_local_ip():
    """获取本机局域网 IP，优先返回真实物理网卡 IP，跳过 VPN/虚拟网卡。"""
    import re
    import subprocess

    # 虚拟/回环网卡前缀，这些 IP 不是真实局域网地址
    # 127.x = 回环; 169.254.x = 未获取DHCP; 198.18.x = 性能测试/VPN虚拟网卡
    virtual_prefixes = ("127.", "169.254.", "198.18.")
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["ipconfig"], capture_output=True, timeout=3
            ).stdout.decode("gbk", errors="ignore")
            ips = re.findall(r"IPv4[^\d]*([\d.]+)", out)
        else:
            out = subprocess.run(
                ["ip", "-4", "addr"], capture_output=True, timeout=3
            ).stdout.decode(errors="ignore")
            ips = re.findall(r"inet ([\d.]+)", out)
        # 优先返回真实局域网 IP（过滤掉虚拟网卡）
        lan_ips = [ip for ip in ips if not ip.startswith(virtual_prefixes)]
        if lan_ips:
            return lan_ips[0]
        if ips:
            return ips[0]
    except Exception:
        pass
    # fallback：UDP 探测默认路由出口 IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    # 行缓冲，确保启动信息立即显示（管道/后台运行时不被块缓冲）
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    # 确保共享目录存在
    os.makedirs(SHARE_DIR, exist_ok=True)

    # 1. 配置授权：匿名用户映射到 SHARE_DIR，赋予读写权限
    authorizer = DummyAuthorizer()
    authorizer.add_anonymous(SHARE_DIR, perm=ANON_PERM)

    # 2. 配置 FTP Handler
    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = BANNER
    # 被动模式端口范围，避免 NAT/防火墙导致数据连接失败
    handler.passive_ports = range(PASV_PORT_START, PASV_PORT_END + 1)
    # UTF-8 编码，避免中文文件名乱码
    handler.encoding = "utf-8"

    # 3. 创建并配置服务器
    server = FTPServer((HOST, PORT), handler)
    server.max_cons = MAX_CONS
    server.max_cons_per_ip = MAX_CONS_PER_IP

    # 4. 打印启动信息
    ip = get_local_ip()
    print("=" * 56)
    print("  FTP 共享服务器已启动")
    print("=" * 56)
    print(f"  本机 IP    : {ip}")
    print(f"  访问地址   : ftp://{ip}:{PORT}")
    print(f"  共享目录   : {SHARE_DIR}")
    print(f"  权限       : 匿名读写（上传 + 下载）")
    print(f"  被动端口   : {PASV_PORT_START}-{PASV_PORT_END}")
    print(f"  最大连接   : {MAX_CONS}（单 IP {MAX_CONS_PER_IP}）")
    print("=" * 56)
    print("  局域网内其他设备访问方式：")
    print(f"    浏览器      : ftp://{ip}:{PORT}")
    print(f"    资源管理器  : 在地址栏输入 ftp://{ip}:{PORT}")
    print("    FTP 客户端  : 主机 {ip} 端口 {port} 匿名登录".format(ip=ip, port=PORT))
    print("-" * 56)
    print("  按 Ctrl+C 停止服务器")
    print()

    # 5. 启动服务（前台阻塞运行）
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止，拜拜~")
        server.close_all()


if __name__ == "__main__":
    main()
