"""双活的真实进程、断网合并、图片完整性和备份恢复验证。"""
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
import zipfile
from unittest.mock import patch
import threading

from clipboard_sync import ClipboardStore, ClipboardSync, rank


class DualClipboardTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.token = 'test-dual-token'
        self.processes, self.envs, self.urls = {}, {}, {}
        sockets = [socket.socket(), socket.socket()]
        for name, sock in zip(('a', 'b'), sockets):
            sock.bind(('127.0.0.1', 0))
            self.urls[name] = 'http://127.0.0.1:' + str(sock.getsockname()[1])
        for sock in sockets:
            sock.close()
        for name in ('a', 'b'):
            root = Path(self.root.name) / name
            self.envs[name] = dict(os.environ, HTTP_HOST='127.0.0.1',
                HTTP_PORT=self.urls[name].rsplit(':', 1)[1], DATA_DIR=str(root / 'data'),
                SHARE_DIR=str(root / 'shared'), FILESHARE_CONFIG=str(root / 'none.env'),
                CLIPBOARD_PRIMARY_URL='', CLIPBOARD_NODE_ID=name,
                CLIPBOARD_PEER_URL=self.urls['b' if name == 'a' else 'a'],
                CLIPBOARD_SYNC_TOKEN=self.token, CLIPBOARD_BACKUP_TOKEN=self.token,
                HTTP_PROXY='http://127.0.0.1:1', NO_PROXY='')
        self.addCleanup(self.stop_all)
        self.start('a')
        self.start('b')

    def stop_all(self):
        for name in list(self.processes):
            self.stop(name)

    def start(self, name):
        self.processes[name] = subprocess.Popen([sys.executable, 'http_server.py'], env=self.envs[name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait(lambda: self.call(name, '/api/list')[0] == 200)

    def stop(self, name):
        process = self.processes.pop(name, None)
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)

    def call(self, name, path='/api/clipboard', method='GET', data=None, auth=False):
        headers = {}
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        if auth:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(self.urls[name] + path, method=method, data=data, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, response.read()

    def items(self, name):
        return json.loads(self.call(name)[1])['items']

    def wait(self, predicate):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return
            except (OSError, KeyError):
                pass
            time.sleep(0.1)
        self.fail('等待双活状态超时')

    def add(self, name, text):
        status, body = self.call(name, method='POST', data={'text': text})
        self.assertEqual(status, 200)
        return json.loads(body)['entry']['id']

    def settled(self, ids):
        for name in ('a', 'b'):
            items = self.items(name)
            if {e['id'] for e in items} != ids or not all(e['synced'] for e in items):
                return False
        return True

    def test_offline_write_images_and_rejoin(self):
        self.stop('b')
        cid = self.add('a', '断网也能保存')
        self.assertFalse(self.items('a')[0]['synced'])
        image = b'\x89PNG\r\n\x1a\n' + b'private-image' * 10000
        body = (b'--probe\r\nContent-Disposition: form-data; name="image"; filename="probe.png"\r\n'
                b'Content-Type: image/png\r\n\r\n' + image + b'\r\n--probe--\r\n')
        request = urllib.request.Request(self.urls['a'] + '/api/clipboard/image', data=body,
            headers={'Content-Type': 'multipart/form-data; boundary=probe'})
        with urllib.request.urlopen(request) as response:
            iid = json.load(response)['entry']['id']
        self.start('b')
        other = self.add('b', '另一台独立发布')
        self.wait(lambda: self.settled({cid, iid, other}))
        self.assertEqual(self.call('b', '/api/clipboard/file/' + iid), (200, image))
        self.stop('a')
        self.assertEqual(self.call('b', '/api/clipboard/file/' + iid), (200, image))
        self.assertEqual(self.call('b', '/api/list')[0], 200)
        self.assertEqual(json.loads(self.call('b', '/api/list')[1])['items'], [])
        self.start('a')
        self.wait(lambda: self.settled({cid, iid, other}))
        status, snapshot = self.call('b', '/api/clipboard/backup', auth=True)
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('clipboard_sync.sqlite3', archive.namelist())
            self.assertEqual(archive.read('clipboard_files/' + iid + '.png'), image)

    def test_partition_concurrent_edits_and_delete_wins(self):
        edit_id = self.add('a', '原文')
        delete_id = self.add('b', '准备删除')
        self.wait(lambda: self.settled({edit_id, delete_id}))
        peers = {name: self.envs[name]['CLIPBOARD_PEER_URL'] for name in ('a', 'b')}
        self.stop_all()
        for name in ('a', 'b'):
            self.envs[name]['CLIPBOARD_PEER_URL'] = 'http://127.0.0.1:1'
            self.start(name)
        for name in ('a', 'b'):
            self.assertEqual(self.call(name, '/api/clipboard/edit', 'POST',
                {'id': edit_id, 'text': name + '的离线编辑'})[0], 200)
        self.assertEqual(self.call('a', '/api/clipboard/' + delete_id, 'DELETE')[0], 200)
        self.assertEqual(self.call('b', '/api/clipboard/edit', 'POST',
            {'id': delete_id, 'text': '离线修改不能复活已删除条目'})[0], 200)
        a_id, b_id = self.add('a', '离线新增A'), self.add('b', '离线新增B')
        records = [next(r for r in json.loads(self.call(name, '/api/clipboard/sync', auth=True)[1])['records']
                        if r['id'] == edit_id) for name in ('a', 'b')]
        expected = max(records, key=rank)['text']
        self.stop_all()
        for name in ('a', 'b'):
            self.envs[name]['CLIPBOARD_PEER_URL'] = peers[name]
            self.start(name)
        self.wait(lambda: self.settled({edit_id, a_id, b_id}))
        for name in ('a', 'b'):
            self.assertEqual(next(e for e in self.items(name) if e['id'] == edit_id)['text'], expected)
            self.assertEqual(self.call(name, '/api/clipboard/' + delete_id, 'DELETE')[0], 404)
        # 恢复完整备份后，删除标记仍然阻止旧版本重新出现。
        _, snapshot = self.call('a', '/api/clipboard/backup', auth=True)
        restored = Path(self.root.name) / 'restored'
        with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
            archive.extractall(restored)
        (restored / 'clipboard_files').mkdir(exist_ok=True)
        store = ClipboardStore(restored, 'a', 200, lambda _: '.png')
        self.assertTrue(store.get(delete_id)['_deleted'])
        stale = {'id': delete_id, 'type': 'text', 'text': '很旧的副本',
                 'created_at': '2026-10-07 00:00:00', '_version': [9999, 'b']}
        store.merge(stale)
        self.assertTrue(store.get(delete_id)['_deleted'])

    def test_auth_and_invalid_sync_never_modify_local_data(self):
        self.assertEqual(self.call('a', '/api/clipboard/sync')[0], 403)
        self.assertEqual(self.call('a', '/api/clipboard/sync', 'POST', {'records': []})[0], 403)
        bad = {'id': '../outside', '_version': [1, 'b'], '_deleted': True}
        self.assertEqual(self.call('a', '/api/clipboard/sync', 'POST', {'records': [bad]}, auth=True)[0], 400)
        self.assertEqual(self.items('a'), [])

    def test_clear_keeps_unseen_offline_additions(self):
        cid = self.add('a', '清空时已知的内容')
        self.wait(lambda: self.settled({cid}))
        self.stop('b')
        self.assertEqual(self.call('a', '/api/clipboard/clear', 'POST')[0], 200)
        peer = self.envs['b']['CLIPBOARD_PEER_URL']
        self.envs['b']['CLIPBOARD_PEER_URL'] = 'http://127.0.0.1:1'
        self.start('b')
        fresh = self.add('b', '断网期间的新内容')
        self.stop('b')
        self.envs['b']['CLIPBOARD_PEER_URL'] = peer
        self.start('b')
        self.wait(lambda: self.settled({fresh}))

    def test_pagination_and_retention_tombstones(self):
        self.stop_all()
        root = Path(self.envs['a']['DATA_DIR'])
        store = ClipboardStore(root, 'a', 200, lambda _: '.png')
        entries = [{'id': uuid.uuid4().hex, 'type': 'text', 'text': str(n),
                    'created_at': f'2026-10-07 00:{n // 60:02d}:{n % 60:02d}'} for n in range(250)]
        store.save(entries)
        self.start('a')
        self.start('b')
        self.wait(lambda: self.settled({e['id'] for e in entries[-200:]}))
        for name in ('a', 'b'):
            with sqlite3.connect(Path(self.envs[name]['DATA_DIR']) / 'clipboard_sync.sqlite3') as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM records').fetchone()[0], 250)

    def test_corrupt_image_is_not_published_or_acknowledged(self):
        root = Path(self.root.name) / 'isolated'
        (root / 'clipboard_files').mkdir(parents=True)
        store = ClipboardStore(root, 'isolated', 200, lambda _: '.png')
        sync = ClipboardSync(store, self.urls['a'], self.token, threading.Lock(), 20 * 1024 * 1024)
        record = {'id': uuid.uuid4().hex, 'type': 'image', 'mime': 'image/png',
                  'created_at': '2026-10-07 00:00:00', '_version': [1, 'a'], '_sha256': '0' * 64}
        record['_file'] = record['id'] + '.png'
        with patch.object(sync, 'request', return_value=io.BytesIO(b'corrupted')):
            with self.assertRaises(ValueError):
                sync.receive([record])
        self.assertIsNone(store.get(record['id']))
        self.assertEqual(list((root / 'clipboard_files').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
