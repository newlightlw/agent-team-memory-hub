from __future__ import annotations

import contextlib
import fcntl
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


class ProcessLock:
    """Reentrant thread lock plus POSIX file lock shared with backup commands."""

    def __init__(self, path):
        self.path = path
        self.thread_lock = threading.RLock()
        self.depth = 0
        self.file = None

    def __enter__(self):
        self.thread_lock.acquire()
        try:
            if self.depth == 0:
                self.file = self.path.open("a")
                self.path.chmod(0o600)
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX)
            self.depth += 1
            return self
        except BaseException:
            if self.file:
                self.file.close()
            self.thread_lock.release()
            raise

    def __exit__(self, *args):
        self.depth -= 1
        if self.depth == 0:
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
        self.thread_lock.release()


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="microseconds")


class Store:
    """SQLite transactions serialize IDs, revisions, votes, and the durable outbox."""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root
        self.path = root / "collaboration.sqlite3"
        self.lock = ProcessLock(root / "gateway.lock")
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA secure_delete=ON;
                CREATE TABLE IF NOT EXISTS records(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, author TEXT NOT NULL,
                    title TEXT NOT NULL, body TEXT NOT NULL, project TEXT NOT NULL,
                    source TEXT NOT NULL, source_url TEXT NOT NULL,
                    created TEXT NOT NULL, updated TEXT NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL,
                    data TEXT NOT NULL, replaced_by TEXT);
                CREATE TABLE IF NOT EXISTS revisions(
                    id TEXT NOT NULL, revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
                    PRIMARY KEY(id, revision));
                CREATE TABLE IF NOT EXISTS links(
                    child TEXT NOT NULL, parent TEXT NOT NULL,
                    PRIMARY KEY(child, parent));
                CREATE TABLE IF NOT EXISTS votes(
                    id TEXT NOT NULL, revision INTEGER NOT NULL, member TEXT NOT NULL,
                    created TEXT NOT NULL, PRIMARY KEY(id, revision, member));
                CREATE TABLE IF NOT EXISTS events(
                    event_id TEXT PRIMARY KEY, record_id TEXT, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, record_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    available REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
                    UNIQUE(kind, record_id));
                CREATE TABLE IF NOT EXISTS counters(
                    day TEXT NOT NULL, author TEXT NOT NULL, value INTEGER NOT NULL,
                    PRIMARY KEY(day, author));
            """)
        self.path.chmod(0o600)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def decode(row):
        if row is None:
            raise KeyError("record not found")
        item = dict(row)
        item["data"] = json.loads(item["data"])
        return item

    def get(self, rid: str, db=None):
        if db is not None:
            return self.decode(db.execute("SELECT * FROM records WHERE id=?", (rid,)).fetchone())
        with self.connect() as db:
            return self.get(rid, db)

    def all(self, *, history=False):
        with self.connect() as db:
            sql = "SELECT * FROM records WHERE status != 'withdrawn'"
            if not history:
                sql += " AND status != 'superseded'"
            return [self.decode(r) for r in db.execute(sql + " ORDER BY updated DESC, id DESC")]

    def save(self, db, item):
        keys = list(item)
        encoded = {**item, "data": json.dumps(item["data"], ensure_ascii=False)}
        db.execute(
            f"INSERT OR REPLACE INTO records ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
            [encoded[k] for k in keys],
        )
        db.execute("INSERT OR REPLACE INTO revisions VALUES(?,?,?)",
                   (item["id"], item["revision"], json.dumps(item, ensure_ascii=False)))

    def create(self, db, *, kind, author, title, body, project="", source="codex",
               source_url="", data=None, parents=(), status="active"):
        day = datetime.now(TZ).strftime("%Y%m%d")
        row = db.execute("SELECT value FROM counters WHERE day=? AND author=?", (day, author)).fetchone()
        seq = row[0] + 1 if row else 1
        if seq > 999:
            raise ValueError("daily member record limit reached")
        db.execute("INSERT OR REPLACE INTO counters VALUES(?,?,?)", (day, author, seq))
        rid = f"mem-{day}-{author}-{seq:03d}"
        for parent in parents:
            if self.get(parent, db)["status"] in ("withdrawn", "superseded"):
                raise ValueError("source must be current")
        item = dict(id=rid, kind=kind, author=author, title=title, body=body,
                    project=project, source=source, source_url=source_url,
                    created=now(), updated=now(), status=status, revision=1,
                    data=data or {}, replaced_by=None)
        self.save(db, item)
        db.executemany("INSERT INTO links VALUES(?,?)", [(rid, p) for p in set(parents)])
        self.enqueue(db, "index", rid)
        self.enqueue(db, "export", "all")
        return item

    def parents(self, rid):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT parent FROM links WHERE child=?", (rid,))]

    def history(self, rid):
        with self.connect() as db:
            self.get(rid, db)
            return [json.loads(r[0]) for r in db.execute(
                "SELECT snapshot FROM revisions WHERE id=? ORDER BY revision", (rid,))]

    def enqueue(self, db, kind, rid):
        db.execute("""INSERT INTO jobs(id,kind,record_id) VALUES(?,?,?)
            ON CONFLICT(kind,record_id) DO UPDATE SET state='pending',available=0,error=''""",
                   (uuid4().hex, kind, rid))

    def withdraw(self, rid: str, author: str):
        with self.transaction() as db:
            item = self.get(rid, db)
            if item["author"] != author:
                raise PermissionError("only the author may withdraw")
            if item["status"] == "withdrawn":
                return []
            # All source-derived material is invalidated conservatively, including
            # earlier revisions. Unrelated records and discussion threads survive.
            rows = db.execute("""WITH RECURSIVE affected(id) AS (
                SELECT ? UNION SELECT child FROM links JOIN affected ON parent=affected.id
                ) SELECT id FROM affected""", (rid,)).fetchall()
            ids = [r[0] for r in rows]
            for affected in ids:
                entry = self.get(affected, db)
                entry.update(title="[已撤回]", body="", source_url="", data={},
                             status="withdrawn", updated=now(), revision=entry["revision"] + 1)
                db.execute("DELETE FROM revisions WHERE id=?", (affected,))
                db.execute("DELETE FROM votes WHERE id=?", (affected,))
                self.save(db, entry)
                db.execute("DELETE FROM jobs WHERE record_id=?", (affected,))
                self.enqueue(db, "delete_index", affected)
            # No source text ever goes into the job payload or events table.
            self.enqueue(db, "purge_export", "all")
            return ids

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY rowid")]
