from __future__ import annotations
from datetime import datetime
import re
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from urllib.parse import quote
from ..models import parse_memory


class Memories:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.cached = None
        self.cached_at = 0

    def snapshot(self, *, force=False):
        with self.lock:
            if not force and self.cached is not None and time.monotonic() - self.cached_at < 5:
                return self.cached
            rows, problems = {}, []
            feishu = {}
            try:
                db_path = Path(self.config['feishu_db']).resolve()
                with sqlite3.connect('file:' + quote(str(db_path)) + '?mode=ro', uri=True) as db:
                    db.row_factory = sqlite3.Row
                    for r in db.execute("SELECT id,title,body,author,source,created,updated,status,revision,source_url FROM records WHERE kind='share' AND source='feishu'"):
                        row = dict(r)
                        feishu[row['id']] = row
                        if row['status'] in ('withdrawn', 'superseded') or row['body'].lstrip().startswith(('/查 ', '/find ')):
                            continue
                        row.update(key='feishu:' + row['id'], origin='feishu', summarized=False, version='修订 ' + str(row['revision']), git_url='')
                        rows[row['key']] = row
            except (OSError, sqlite3.Error):
                problems.append('飞书来源暂时不可用')
            commit = ''
            try:
                root = Path(self.config['git_root'])
                def git(*args):
                    r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=15)
                    if r.returncode:
                        raise ValueError('Git snapshot unavailable')
                    return r.stdout
                commit = git('rev-parse', 'HEAD').strip()
                for item in git('ls-tree', '-r', '-l', '-z', commit, '--', 'memory').split('\0'):
                    if not item:
                        continue
                    meta, path = item.split('\t', 1)
                    mode, kind, sha, size = meta.split()
                    if mode not in ('100644', '100755') or kind != 'blob' or not path.endswith('.md') or int(size) > 256000:
                        continue
                    entry = parse_memory(git('show', commit + ':' + path))
                    if entry.status.value != 'active' or entry.scope.value == 'personal':
                        continue
                    origin = 'feishu' if entry.source == 'feishu' else 'agent'
                    original = None
                    if origin == 'feishu':
                        evidence = entry.body.split('## 来源与证据', 1)[-1].split('## 原始资料', 1)[0]
                        match = re.search(r'\bmem-\d{8}-[a-z0-9_]+-\d{3}\b', evidence)
                        original = feishu.get(match.group(0)) if match else None
                        # The service remains authoritative for withdrawals. Fail closed.
                        if not original or original['status'] in ('withdrawn', 'superseded'):
                            continue
                        revision = re.search(r'\brevision=(\d+)\b', entry.body.split('## 目的', 1)[0])
                        if not revision or int(revision.group(1)) != original['revision']:
                            continue  # Keep the current raw source until its summary catches up.
                    key = 'feishu:' + original['id'] if original else 'git:' + entry.id
                    rows[key] = dict(key=key, id=original['id'] if original else entry.id,
                        title=original['title'] if original else entry.title, body=entry.body,
                        author=original['author'] if original else entry.author, source=entry.source,
                        created=original['created'] if original else entry.created,
                        updated=original['updated'] if original else (entry.updated or entry.created),
                        status=original['status'] if original else entry.status.value,
                        origin=origin, summarized=True, version=commit[:8],
                        git_url='https://github.com/' + self.config['repo'] + '/blob/' + commit + '/' + path)
            except (OSError, ValueError, subprocess.SubprocessError):
                problems.append('Git 记忆暂时不可用')
            sync_file = Path(self.config['git_root']).parent / 'last-sync'
            synced = sync_file.read_text().strip() if sync_file.exists() else ''
            value = {'records': sorted(rows.values(), key=lambda r: (r['updated'], r['id']), reverse=True),
                     'commit': commit, 'git_synced_at': synced, 'warnings': problems}
            self.cached, self.cached_at = value, time.monotonic()
            return value
