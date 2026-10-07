"""为已有服务启用剪切板双活，只更新运行配置，不修改共享文件目录。"""
import argparse
import os
from pathlib import Path
import subprocess

BASE = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--peer', required=True)
    args = parser.parse_args()
    token = os.environ.get('CLIPBOARD_SYNC_TOKEN', '')
    if not token:
        parser.error('请通过 CLIPBOARD_SYNC_TOKEN 环境变量传入共同的同步密钥')
    config = BASE / 'server.env'
    values = dict(line.split('=', 1) for line in config.read_text(encoding='utf-8').splitlines()
                  if line.strip() and not line.lstrip().startswith('#'))
    data = Path(values.get('DATA_DIR') or BASE / 'data')
    folder = data / 'configuration-backups'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    old = folder / 'server-before-dual.env'
    if not old.exists():
        old.touch(mode=0o600)
        if os.name == 'nt':
            subprocess.run(['icacls', str(old), '/inheritance:r', '/grant:r',
                            '*S-1-5-18:F', '*S-1-5-32-544:F'], check=True, stdout=subprocess.DEVNULL)
        old.write_bytes(config.read_bytes())
    values.update(CLIPBOARD_PRIMARY_URL='', CLIPBOARD_NODE_ID=args.node,
                  CLIPBOARD_PEER_URL=args.peer.rstrip('/'), CLIPBOARD_SYNC_TOKEN=token)
    # 原位写入保留 NAS 文件所有者和 Windows 的私密 ACL。
    config.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    print('剪切板双活配置完成：' + args.node)


if __name__ == '__main__':
    main()
