"""双节点剪切板：本地事务保存、确定性合并、永久删除标记和图片校验。"""
import hashlib
from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import urllib.parse
import urllib.request


def version(record):
    return tuple(record['_version'])


def rank(record):
    # 删除永久胜出；同一条目的并发编辑按逻辑版本和节点名确定唯一结果。
    return (bool(record.get('_deleted')), version(record))


def public(record):
    return {key: value for key, value in record.items() if not key.startswith('_')}


def validate(record):
    if not isinstance(record, dict) or not re.fullmatch(r'[0-9a-f]{32}', record.get('id', '')):
        raise ValueError('无效条目 ID')
    rev = record.get('_version')
    if (not isinstance(rev, list) or len(rev) != 2 or type(rev[0]) is not int or
            not 0 <= rev[0] < 2**63 - 1 or not isinstance(rev[1], str) or
            not re.fullmatch(r'[a-zA-Z0-9-]{1,48}', rev[1])):
        raise ValueError('无效版本')
    if type(record.get('_deleted', False)) is not bool:
        raise ValueError('无效删除标记')
    if record.get('_deleted'):
        return
    if record.get('type') == 'text':
        text = record.get('text')
        if not isinstance(text, str) or len(text.encode('utf-8')) > 100 * 1024:
            raise ValueError('无效文字')
    elif record.get('type') == 'image':
        if (not re.fullmatch(re.escape(record['id']) + r'\.[a-zA-Z0-9]{1,10}', record.get('_file', '')) or
                not re.fullmatch(r'[0-9a-f]{64}', record.get('_sha256', ''))):
            raise ValueError('无效图片')
    else:
        raise ValueError('无效条目类型')
    if not isinstance(record.get('created_at'), str):
        raise ValueError('缺少创建时间')


class ClipboardStore:
    def __init__(self, data_dir, node, limit, image_ext):
        if not re.fullmatch(r'[a-zA-Z0-9-]{1,48}', node):
            raise ValueError('无效剪切板节点名')
        self.root = Path(data_dir)
        self.db = self.root / 'clipboard_sync.sqlite3'
        self.images = self.root / 'clipboard_files'
        self.node, self.limit, self.image_ext = node, limit, image_ext
        self.lock = threading.RLock()
        self.wakeup = threading.Event()
        self.connected = False
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT NOT NULL, ack TEXT NOT NULL DEFAULT "")')
            conn.execute('CREATE TABLE IF NOT EXISTS clock (value INTEGER NOT NULL)')
            if not conn.execute('SELECT value FROM clock').fetchone():
                conn.execute('INSERT INTO clock VALUES (0)')
            # 每次启动都重新确认对端副本，避免恢复旧备份后错误显示同步成功。
            conn.execute('UPDATE records SET ack=""')
        legacy = self.root / 'clipboard.json'
        if not self.page() and legacy.exists():
            self.save(json.loads(legacy.read_text(encoding='utf-8')))
        if legacy.exists():
            legacy.replace(self.root / 'clipboard-imported.json')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db, timeout=30)
        try:
            conn.execute('PRAGMA synchronous=FULL')
            with conn:
                yield conn
        finally:
            conn.close()

    def page(self, after='', limit=100):
        with self.lock, self.connect() as conn:
            return [json.loads(row[0]) for row in conn.execute(
                'SELECT payload FROM records WHERE id>? ORDER BY id LIMIT ?', (after, limit))]

    def get(self, cid):
        with self.lock, self.connect() as conn:
            row = conn.execute('SELECT payload FROM records WHERE id=?', (cid,)).fetchone()
            return json.loads(row[0]) if row else None

    def entries(self, status=False):
        with self.lock, self.connect() as conn:
            result = []
            for payload, ack in conn.execute('SELECT payload,ack FROM records'):
                record = json.loads(payload)
                if not record.get('_deleted'):
                    entry = public(record)
                    if status:
                        entry['synced'] = ack == json.dumps(record['_version'])
                    result.append(entry)
            return sorted(result, key=lambda entry: (entry['created_at'], entry['id']))

    def _next(self, conn):
        conn.execute('UPDATE clock SET value=value+1')
        return [conn.execute('SELECT value FROM clock').fetchone()[0], self.node]

    def _put(self, conn, record, ack=''):
        conn.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)',
                     (record['id'], json.dumps(record, ensure_ascii=False), ack))

    def _trim(self, conn):
        active = [json.loads(row[0]) for row in conn.execute('SELECT payload FROM records')]
        active = sorted((r for r in active if not r.get('_deleted')),
                        key=lambda r: (r['created_at'], r['id']))
        if self.limit > 0:
            for record in active[:-self.limit]:
                self._put(conn, {'id': record['id'], '_deleted': True, '_version': self._next(conn)})

    def save(self, entries):
        with self.lock, self.connect() as conn:
            old = {r['id']: r for r in (json.loads(row[0]) for row in conn.execute('SELECT payload FROM records'))}
            incoming = {entry['id']: entry for entry in entries}
            for cid, record in old.items():
                if not record.get('_deleted') and cid not in incoming:
                    self._put(conn, {'id': cid, '_deleted': True, '_version': self._next(conn)})
            for cid, entry in incoming.items():
                previous = old.get(cid)
                if previous and previous.get('_deleted'):
                    continue
                if previous and public(previous) == entry:
                    continue
                record = dict(entry, _version=self._next(conn))
                if entry['type'] == 'image':
                    name = cid + self.image_ext(entry.get('mime'))
                    if not (self.images / name).exists():
                        candidates = list(self.images.glob(cid + '.*'))
                        if len(candidates) != 1:
                            raise ValueError('找不到原始图片文件')
                        name = candidates[0].name
                    record['_file'] = name
                    record['_sha256'] = hashlib.sha256((self.images / name).read_bytes()).hexdigest()
                validate(record)
                self._put(conn, record)
            self._trim(conn)
        self.cleanup_images()
        self.wakeup.set()

    def merge(self, record):
        validate(record)
        with self.lock, self.connect() as conn:
            row = conn.execute('SELECT payload FROM records WHERE id=?', (record['id'],)).fetchone()
            old = json.loads(row[0]) if row else None
            conn.execute('UPDATE clock SET value=MAX(value,?)', (record['_version'][0],))
            if old is None or rank(record) > rank(old):
                self._put(conn, record, json.dumps(record['_version']))
            elif record == old:
                conn.execute('UPDATE records SET ack=? WHERE id=?',
                             (json.dumps(record['_version']), record['id']))
            self._trim(conn)
        # 只有数据库删除已提交后才能移除图片；备份和调用方共用剪切板锁。
        self.cleanup_images()

    def cleanup_images(self):
        with self.lock, self.connect() as conn:
            deleted = {r['id'] for r in (json.loads(row[0]) for row in conn.execute('SELECT payload FROM records')) if r.get('_deleted')}
        for path in self.images.iterdir():
            if path.stem in deleted:
                path.unlink(missing_ok=True)

    def acknowledge(self, record):
        with self.lock, self.connect() as conn:
            row = conn.execute('SELECT payload FROM records WHERE id=?', (record['id'],)).fetchone()
            if row and json.loads(row[0]) == record:
                conn.execute('UPDATE records SET ack=? WHERE id=?',
                             (json.dumps(record['_version']), record['id']))

    def backup_database(self, path):
        with self.lock, self.connect() as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)


class ClipboardSync:
    def __init__(self, store, peer, token, lock, image_limit):
        if not peer.startswith(('http://', 'https://')) or not token:
            raise ValueError('双活需要对端地址和同步密钥')
        self.store, self.peer, self.token = store, peer.rstrip('/'), token
        self.lock, self.image_limit = lock, image_limit
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.last_error = None

    def request(self, path, body=None):
        headers = {'Authorization': 'Bearer ' + self.token}
        if body is not None:
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        return self.opener.open(urllib.request.Request(self.peer + path, data=body, headers=headers), timeout=30)

    def prepare(self, record):
        validate(record)
        old = self.store.get(record['id'])
        if record.get('_deleted') or (old and rank(old) > rank(record)) or record.get('type') != 'image':
            return
        path = self.store.images / record['_file']
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == record['_sha256']:
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.store.images, delete=False) as target:
                temporary = Path(target.name)
                digest, size = hashlib.sha256(), 0
                with self.request('/api/clipboard/sync/file/' + record['id']) as response:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > self.image_limit:
                            raise ValueError('同步图片超过上限')
                        target.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != record['_sha256']:
                    raise ValueError('同步图片校验失败')
                target.flush()
                os.fsync(target.fileno())
            with self.lock:
                os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def receive(self, records):
        if not isinstance(records, list) or len(records) > 100:
            raise ValueError('同步批次最多 100 条')
        for record in records:
            self.prepare(record)
            with self.lock:
                self.store.merge(record)
        return [self.store.get(record['id']) for record in records]

    def cycle(self):
        cursor = ''
        while True:
            with self.request('/api/clipboard/sync?after=' + urllib.parse.quote(cursor)) as response:
                records = json.load(response)['records']
            self.receive(records)
            if len(records) < 100:
                break
            cursor = records[-1]['id']
        cursor = ''
        while True:
            records = self.store.page(cursor)
            if not records:
                break
            with self.request('/api/clipboard/sync', {'records': records}) as response:
                confirmed = json.load(response)['records']
            self.receive(confirmed)
            for record in confirmed:
                self.store.acknowledge(record)
            cursor = records[-1]['id']
        self.store.connected = True

    def run(self):
        while True:
            self.store.wakeup.clear()
            try:
                self.cycle()
                self.last_error = None
            except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
                if self.last_error != type(error).__name__:
                    print('剪切板对端暂时不可用：' + type(error).__name__)
                self.last_error = type(error).__name__
                self.store.connected = False
            self.store.wakeup.wait(2)
