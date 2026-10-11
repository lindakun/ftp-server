"""三节点真实进程验证：故障隔离、图片转发、独立副本确认和已有数据合并。"""
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import time
import zipfile
from unittest.mock import patch

from clipboard_sync import ClipboardStore, ClipboardSync, rank
from test_clipboard_dual import ClipboardProcessTest


class MultiClipboardTest(ClipboardProcessTest):
    nodes = ('a', 'b', 'c')

    def image(self, name):
        content = b'\x89PNG\r\n\x1a\n' + b'multi-node-image' * 10000
        body = (b'--probe\r\nContent-Disposition: form-data; name="image"; filename="probe.png"\r\n'
                b'Content-Type: image/png\r\n\r\n' + content + b'\r\n--probe--\r\n')
        import urllib.request
        request = urllib.request.Request(self.urls[name] + '/api/clipboard/image', data=body,
            headers={'Content-Type': 'multipart/form-data; boundary=probe'})
        with urllib.request.urlopen(request) as response:
            return json.load(response)['entry']['id'], content

    def test_each_node_failure_remaining_pair_and_rejoin(self):
        ids = set()
        for missing in self.nodes:
            self.stop(missing)
            remaining = [n for n in self.nodes if n != missing]
            cid = self.add(remaining[0], '重复内容也保留')
            ids.add(cid)
            def pair_ready():
                for name in remaining:
                    entry = next((e for e in self.items(name) if e['id'] == cid), {})
                    if entry.get('replicas') != 2 or entry.get('pending_nodes') != [missing] or entry.get('synced'):
                        return False
                return True
            self.wait(pair_ready)
            iid, content = self.image(remaining[1])
            ids.add(iid)
            self.wait(lambda: self.call(remaining[0], '/api/clipboard/file/' + iid) == (200, content))
            self.start(missing)
            self.wait(lambda: self.settled(ids))
            self.assertEqual(self.call(missing, '/api/clipboard/file/' + iid), (200, content))
        for name in self.nodes:
            self.assertEqual(len([e for e in self.items(name) if e.get('text') == '重复内容也保留']), 3)
            self.assertEqual(json.loads(self.call(name, '/api/list')[1])['items'], [])

    def test_relay_fetches_image_from_sender_not_original_author(self):
        self.stop_all()
        for name, peers in {'a': ['b'], 'b': ['a', 'c'], 'c': ['b']}.items():
            self.envs[name]['CLIPBOARD_PEERS'] = json.dumps({p: self.urls[p] for p in peers})
        self.start('a')
        iid, content = self.image('a')
        self.start('b')
        self.wait(lambda: self.call('b', '/api/clipboard/file/' + iid) == (200, content))
        self.stop('a')
        self.start('c')
        self.wait(lambda: self.call('c', '/api/clipboard/file/' + iid) == (200, content))
        record = json.loads(self.call('c', '/api/clipboard/sync', auth=True, sender='b')[1])['records'][0]
        self.assertEqual(record['_version'][1], 'a')
        self.wait(lambda: self.items('c')[0]['synced'])

    def test_slow_cloud_peer_does_not_block_local_pair(self):
        release, connected = threading.Event(), threading.Event()
        class SlowPeer(BaseHTTPRequestHandler):
            def do_GET(self):
                connected.set()
                release.wait(20)
                self.send_error(503)

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), SlowPeer)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.stop_all()
        for name in ('a', 'b'):
            peers = json.loads(self.envs[name]['CLIPBOARD_PEERS'])
            peers['c'] = 'http://127.0.0.1:' + str(server.server_port)
            self.envs[name]['CLIPBOARD_PEERS'] = json.dumps(peers)
            self.start(name)
        self.assertTrue(connected.wait(3))
        started = time.monotonic()
        cid = self.add('a', '慢云连接不能阻塞本地同步')
        self.wait(lambda: any(e['id'] == cid and e['replicas'] == 2 for e in self.items('b')))
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse(next(e for e in self.items('a') if e['id'] == cid)['synced'])

    def test_three_way_partition_edit_delete_and_backup_restore(self):
        edited = self.add('a', '原文')
        deleted = self.add('b', '将删除')
        self.wait(lambda: self.settled({edited, deleted}))
        self.stop_all()
        saved = {n: self.envs[n]['CLIPBOARD_PEERS'] for n in self.nodes}
        for name in self.nodes:
            self.envs[name]['CLIPBOARD_PEERS'] = json.dumps({p: 'http://127.0.0.1:' + str(i + 1)
                for i, p in enumerate(self.nodes) if p != name})
            self.start(name)
            self.assertEqual(self.call(name, '/api/clipboard/edit', 'POST', {'id': edited, 'text': name})[0], 200)
        self.assertEqual(self.call('a', '/api/clipboard/' + deleted, 'DELETE')[0], 200)
        self.assertEqual(self.call('c', '/api/clipboard/edit', 'POST', {'id': deleted, 'text': '离线修改'})[0], 200)
        records = [next(r for r in json.loads(self.call(n, '/api/clipboard/sync', auth=True)[1])['records']
            if r['id'] == edited) for n in self.nodes]
        expected = max(records, key=rank)['text']
        self.stop_all()
        for name in self.nodes:
            self.envs[name]['CLIPBOARD_PEERS'] = saved[name]
            self.start(name)
        self.wait(lambda: self.settled({edited}))
        for name in self.nodes:
            self.assertEqual(self.items(name)[0]['text'], expected)
        _, snapshot = self.call('c', '/api/clipboard/backup', auth=True)
        restored = Path(self.root.name) / 'restored'
        with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
            self.assertIsNone(archive.testzip())
            archive.extractall(restored)
        store = ClipboardStore(restored, 'c', 200, lambda _: '.png')
        for peer in ('a', 'b'):
            ClipboardSync(store, self.urls[peer], self.token, threading.Lock(), 1024, peer)
        self.assertTrue(store.get(deleted)['_deleted'])
        self.assertEqual(store.entries(status=True)[0]['replicas'], 1)
        self.assertFalse(store.entries(status=True)[0]['synced'])

    def test_unknown_sender_and_wrong_peer_identity(self):
        self.assertEqual(self.call('a', '/api/clipboard/sync', auth=True, sender='unknown')[0], 403)
        self.assertEqual(self.call('a', '/api/clipboard/sync', 'POST', {'records': []}, auth=True, sender='unknown')[0], 403)
        root = Path(self.root.name) / 'isolated'
        (root / 'clipboard_files').mkdir(parents=True)
        store = ClipboardStore(root, 'isolated', 200, lambda _: '.png')
        sync = ClipboardSync(store, self.urls['a'], self.token, threading.Lock(), 1024, 'expected')
        with patch.object(sync, 'request', return_value=io.BytesIO(b'{"node":"wrong","records":[]}')):
            with self.assertRaises(ValueError):
                sync.cycle()
        self.assertFalse(store.peers['expected']['online'])

    def test_legacy_cloud_import_keeps_duplicate_content_and_colliding_ids(self):
        cid = self.add('a', '相同内容')
        self.wait(lambda: self.settled({cid}))
        self.stop('c')
        root = Path(self.envs['c']['DATA_DIR'])
        (root / 'clipboard_sync.sqlite3').unlink()
        legacy = [{'id': cid, 'type': 'text', 'text': '相同内容', 'created_at': '2026-10-11 12:00:00'}]
        (root / 'clipboard.json').write_text(json.dumps(legacy), encoding='utf-8')
        config = root / 'test.env'
        config.write_text('DATA_DIR=' + str(root) + '\nCLIPBOARD_SYNC_TOKEN=' + self.token + '\n', encoding='utf-8')
        subprocess.run([sys.executable, 'deploy/configure_dual.py', '--node', 'c', '--config', str(config),
            '--peers', self.envs['c']['CLIPBOARD_PEERS'], '--rekey-legacy'], check=True, stdout=subprocess.DEVNULL)
        migrated = json.loads((root / 'clipboard.json').read_text())[0]['id']
        self.assertNotEqual(migrated, cid)
        self.start('c')
        self.wait(lambda: self.settled({cid, migrated}))
        for name in self.nodes:
            self.assertEqual([e['text'] for e in self.items(name)], ['相同内容', '相同内容'])


if __name__ == '__main__':
    import unittest
    unittest.main()
