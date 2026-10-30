from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from .backup import purge_managed_backups
from .projection import export
from .store import TZ, now

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, service, *, semantic=None, feishu=None):
        self.service, self.store = service, service.store
        self.semantic, self.feishu = semantic, feishu
        with self.store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS deliveries(
                record_id TEXT NOT NULL, message_id TEXT NOT NULL,
                PRIMARY KEY(record_id, message_id))""")
            db.execute("CREATE TABLE IF NOT EXISTS external_index(record_id TEXT PRIMARY KEY)")
            db.execute("UPDATE jobs SET state='pending' WHERE state='running'")

    def tick(self):
        # The single-process gateway serializes outward side effects with
        # mutations. A withdrawal cannot race a stale import/send.
        with self.store.lock:
            with self.store.connect() as db:
                row = db.execute("""SELECT * FROM jobs WHERE state='pending' AND available<=?
                    ORDER BY CASE kind WHEN 'purge_export' THEN 0 WHEN 'delete_index' THEN 1 ELSE 2 END,
                    rowid LIMIT 1""", (time.time(),)).fetchone()
                if not row:
                    return False
                job = dict(row)
                db.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],))
            try:
                self.execute(job)
            except Exception as exc:
                with self.store.connect() as db:
                    db.execute("""UPDATE jobs SET state='pending', attempts=attempts+1,
                        available=?,error=? WHERE id=?""", (
                        time.time() + min(300, 2 ** min(job["attempts"] + 1, 8)),
                        type(exc).__name__, job["id"]))
                logger.warning("collaboration job %s deferred (%s)", job["kind"], type(exc).__name__)
            else:
                with self.store.connect() as db:
                    db.execute("UPDATE jobs SET state='done',error='' WHERE id=?", (job["id"],))
            return True

    def send(self, item, card=False):
        if self.feishu is None:
            raise RuntimeError("Feishu not available")
        message_id = self.feishu.send(item, card=card)
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?)", (item["id"], message_id))

    def execute(self, job):
        kind, rid = job["kind"], job["record_id"]
        if kind in ("export", "purge_export"):
            export(self.store, purge=kind == "purge_export")
            if kind == "purge_export":
                purge_managed_backups(self.store)
                with self.store.connect() as db:
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    db.execute("VACUUM")
            return
        if kind == "delete_index":
            with self.store.connect() as db:
                indexed = db.execute("SELECT 1 FROM external_index WHERE record_id=?", (rid,)).fetchone()
            if indexed and self.semantic is None:
                raise RuntimeError("Mem0 cleanup requires configured provider")
            if self.semantic and indexed:
                self.semantic.delete(rid)
                with self.store.connect() as db:
                    db.execute("DELETE FROM external_index WHERE record_id=?", (rid,))
            with self.store.connect() as db:
                messages = [r[0] for r in db.execute("SELECT message_id FROM deliveries WHERE record_id=?", (rid,))]
            for message_id in messages:
                self.feishu.delete(message_id)
                with self.store.connect() as db:
                    db.execute("DELETE FROM deliveries WHERE record_id=? AND message_id=?", (rid, message_id))
            return
        item = self.store.get(rid)
        if item["status"] == "withdrawn":
            return
        if kind == "index":
            if self.semantic:
                with self.store.connect() as db:
                    db.execute("INSERT OR IGNORE INTO external_index VALUES(?)", (rid,))
                self.semantic.index(item)
        elif kind == "decision_card":
            try:
                self.service.require_confirmation()
            except ValueError:
                return  # Do not send old pending cards after membership changes.
            self.send(item, card=True)
        elif kind == "send":
            self.send(item)
        elif kind == "query_reply":
            query = item["body"].split(" ", 1)[1]
            result = self.service.search(query, semantic=self.semantic)
            # Keep exact source dependencies so retracting a source retracts
            # its outbound search response too. Do not include the query itself.
            found = [r for r in result["results"] if r["id"] != rid][:5]
            text = "\n".join(f'{r["title"]} · {r["author"]} · {r["updated"][:10]} · {r["status"]}\n{r["id"]}' for r in found) or "未找到依据"
            with self.store.transaction() as db:
                if db.execute("SELECT 1 FROM events WHERE event_id=?", ("query_reply:" + rid,)).fetchone():
                    return
                response = self.store.create(db, kind="response", author=item["author"],
                    title="检索结果", body=text, source="service", parents=[rid] + [r["id"] for r in found])
                db.execute("INSERT INTO events VALUES(?,?,?)", ("query_reply:" + rid, response["id"], now()))
                self.store.enqueue(db, "send", response["id"])
        else:
            raise ValueError("unknown job")

    def schedule_digest(self):
        s = self.service.settings
        moment = datetime.now(TZ)
        if not s.digest_enabled or moment.hour < s.digest_hour:
            return
        day = moment.date().isoformat()
        event_id = "digest:" + day
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM events WHERE event_id=?", (event_id,)).fetchone():
                return
            digest = self.service.digest(day)
            if not digest:
                return
            items = digest["items"]
            text = "今日共享变化（按来源摘录，未自动形成共识）\n" + "\n".join(
                f'{r["author"]} · {r["title"]} [{r["status"]}]\n{r["id"]}' for r in items[:15])
            record = self.store.create(db, kind="digest", author=s.members[0].id, title=day + " 共享简报",
                body=text, source="service", parents=[r["id"] for r in items[:15]])
            db.execute("INSERT INTO events VALUES(?,?,?)", (event_id, record["id"], now()))
            self.store.enqueue(db, "send", record["id"])

    def run(self, stop):
        while not stop.is_set():
            try:
                self.schedule_digest()
                if not self.tick():
                    stop.wait(1)
            except Exception as exc:
                logger.warning("collaboration worker deferred (%s)", type(exc).__name__)
                stop.wait(2)
