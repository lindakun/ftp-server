"""安装或运行剪切板节点到云端的常驻 SSH 双向隧道。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from xml.sax.saxutils import escape

BASE = Path(__file__).resolve().parent.parent


def executable(name):
    return shutil.which(name) or str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'OpenSSH' / (name + '.exe'))


def install(args):
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'nt':
        subprocess.run(['icacls', str(root), '/inheritance:r', '/grant:r',
                        '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'], check=True, stdout=subprocess.DEVNULL)
    key = root / 'id_ed25519'
    if not key.exists():
        subprocess.run([executable('ssh-keygen'), '-q', '-t', 'ed25519', '-N', '', '-f', str(key),
                        '-C', 'fileshare-' + args.node], check=True)
    if os.name == 'nt':
        # 隧道任务由 SYSTEM 运行，私钥也必须归 SYSTEM 所有且仅该账户可读。
        subprocess.run(['takeown', '/f', str(key), '/a'],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['icacls', str(key), '/reset'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['icacls', str(key), '/inheritance:r', '/grant:r', '*S-1-5-18:F'],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['icacls', str(key), '/setowner', '*S-1-5-18'],
                       check=True, stdout=subprocess.DEVNULL)
    hosts = root / 'known_hosts'
    hosts.write_text(args.known_host.strip() + '\n', encoding='utf-8')
    config = root / 'tunnel.json'
    values = dict(cloud=args.cloud, cloud_port=args.cloud_port, local_host=args.local_host,
                  local_port=args.local_port, forward_port=args.forward_port, reverse_port=args.reverse_port,
                  identity=str(key), known_hosts=str(hosts))
    config.write_text(json.dumps(values), encoding='utf-8')
    if os.name == 'nt':
        sys.path.insert(0, str(BASE))
        from install_service import gen_xml
        arguments = f'deploy\\clipboard_tunnel.py --config "{config}"'
        xml = gen_xml('FileShareClipboardTunnel', '共享剪切板云端隧道',
                      str(BASE / '.venv' / 'Scripts' / 'pythonw.exe'), escape(arguments), str(BASE))
        task = root / 'task.xml'
        try:
            task.write_text(xml, encoding='utf-16')
            subprocess.run(['schtasks', '/create', '/tn', 'FileShareClipboardTunnel', '/xml', str(task), '/f'], check=True)
        finally:
            task.unlink(missing_ok=True)
    else:
        import pwd
        account = pwd.getpwnam(args.user)
        for path in [root, *root.iterdir()]:
            os.chown(path, account.pw_uid, account.pw_gid)
            path.chmod(0o700 if path.is_dir() else 0o600)
        unit = f'''[Unit]
Description=Clipboard cloud SSH tunnel
After=network-online.target
Wants=network-online.target

[Service]
User={args.user}
ExecStart=/usr/bin/python3 "{BASE}/deploy/clipboard_tunnel.py" --config "{config}"
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={root}
UMask=0077

[Install]
WantedBy=multi-user.target
'''
        Path('/etc/systemd/system/fileshare-clipboard-tunnel.service').write_text(unit, encoding='utf-8')
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
    # 只输出公钥；先在云端授权，再启动任务或服务。
    print(key.with_suffix('.pub').read_text().strip())


def run(config):
    values = json.loads(config.read_text(encoding='utf-8'))
    command = [executable('ssh'), '-N', '-T', '-F', 'none', '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'ExitOnForwardFailure=yes',
               '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3', '-o', 'ConnectTimeout=10',
               '-o', 'IdentitiesOnly=yes', '-o', 'UserKnownHostsFile=' + values['known_hosts'],
               '-i', values['identity'],
               '-L', f"127.0.0.1:{values['forward_port']}:127.0.0.1:{values['cloud_port']}",
               '-R', f"127.0.0.1:{values['reverse_port']}:{values['local_host']}:{values['local_port']}",
               values['cloud']]
    delay = 3
    while True:
        started = time.monotonic()
        if os.name == 'nt':
            with (config.parent / 'tunnel.log').open('a', encoding='utf-8') as log:
                result = subprocess.run(command, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            result = subprocess.run(command)
            print('SSH 隧道退出，稍后重连：' + str(result.returncode), flush=True)
        delay = 3 if time.monotonic() - started > 60 else min(delay * 2, 60)
        time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--node')
    parser.add_argument('--user')
    parser.add_argument('--cloud')
    parser.add_argument('--cloud-port', type=int, default=18080)
    parser.add_argument('--local-host', default='127.0.0.1')
    parser.add_argument('--local-port', type=int, default=8080)
    parser.add_argument('--forward-port', type=int, default=18081)
    parser.add_argument('--reverse-port', type=int)
    parser.add_argument('--known-host', help='通过可信连接核实的云端 SSH 主机公钥行')
    args = parser.parse_args()
    if args.install:
        if not all((args.directory, args.node, args.cloud, args.reverse_port, args.known_host)) or (os.name != 'nt' and not args.user):
            parser.error('安装需要目录、节点名、云端地址、反向端口、可信主机公钥；Linux 还需要 --user')
        install(args)
    elif args.config:
        run(args.config)
    else:
        parser.error('请指定 --install 或 --config')


if __name__ == '__main__':
    main()
