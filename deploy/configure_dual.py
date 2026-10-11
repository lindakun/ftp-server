"""为已有服务配置剪切板多活，不修改共享文件目录。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import uuid

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from clipboard_sync import peer_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--peer', help='兼容旧双节点配置的对端 URL')
    parser.add_argument('--peers', help='对端节点名与 URL 的 JSON 映射')
    parser.add_argument('--config', type=Path, default=Path(os.environ.get('FILESHARE_CONFIG') or BASE / 'server.env'))
    parser.add_argument('--rekey-legacy', action='store_true', help='为独立单机数据分配新 ID，保留与集群内容相同的记录；需先停止服务')
    args = parser.parse_args()
    config = args.config
    values = dict(line.split('=', 1) for line in config.read_text(encoding='utf-8').splitlines()
                  if line.strip() and not line.lstrip().startswith('#'))
    token = os.environ.get('CLIPBOARD_SYNC_TOKEN') or values.get('CLIPBOARD_SYNC_TOKEN', '')
    if not token:
        parser.error('请通过 CLIPBOARD_SYNC_TOKEN 环境变量传入共同的同步密钥')
    if bool(args.peer) == bool(args.peers):
        parser.error('请指定 --peer 或 --peers 其中一种')
    try:
        peers = peer_config(args.node, json.loads(args.peers) if args.peers else None, args.peer or '')
    except (ValueError, TypeError) as error:
        parser.error(str(error))
    data = Path(values.get('DATA_DIR') or BASE / 'data')
    folder = data / 'configuration-backups'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    old = folder / ('server-before-multi-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.env')
    old.touch(mode=0o600)
    if os.name == 'nt':
        subprocess.run(['icacls', str(old), '/inheritance:r', '/grant:r',
                        '*S-1-5-18:F', '*S-1-5-32-544:F'], check=True, stdout=subprocess.DEVNULL)
    old.write_bytes(config.read_bytes())
    if args.rekey_legacy:
        if (data / 'clipboard_sync.sqlite3').exists():
            parser.error('已有同步数据库，不能重复迁移单机数据')
        legacy = data / 'clipboard.json'
        if legacy.exists():
            entries = json.loads(legacy.read_text(encoding='utf-8'))
            snapshot = folder / ('clipboard-before-import-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
            snapshot.touch(mode=0o600)
            snapshot.write_bytes(legacy.read_bytes())
            images = data / 'clipboard_files'
            for entry in entries:
                previous, entry['id'] = entry['id'], uuid.uuid4().hex
                for image in images.glob(previous + '.*'):
                    image.replace(images / (entry['id'] + image.suffix))
            legacy.write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
    values.update(CLIPBOARD_PRIMARY_URL='', CLIPBOARD_NODE_ID=args.node,
                  CLIPBOARD_PEER_URL=(args.peer or '').rstrip('/'),
                  CLIPBOARD_PEERS=json.dumps(peers, separators=(',', ':')) if args.peers else '',
                  CLIPBOARD_SYNC_TOKEN=token)
    values['CLIPBOARD_BACKUP_TOKEN'] = values.get('CLIPBOARD_BACKUP_TOKEN') or secrets.token_urlsafe(32)
    # 原位写入保留 NAS 文件所有者和 Windows 的私密 ACL。
    config.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    print('剪切板多活配置完成：' + args.node)


if __name__ == '__main__':
    main()
