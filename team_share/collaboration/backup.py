from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

from .store import Store, TZ


def backup(store: Store, destination: Path, key: str) -> Path:
    """Online SQLite snapshot, encrypted before any archive is written."""
    cipher = Fernet(key.encode())
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with store.lock, tempfile.TemporaryDirectory(dir=store.root) as temporary:
        snapshot = Path(temporary) / "collaboration.sqlite3"
        with store.connect() as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode="w:gz") as archive:
            archive.add(snapshot, arcname="collaboration.sqlite3")
        out = destination / (datetime.now(TZ).strftime("%Y%m%d-%H%M%S-%f") + ".fernet")
        out.write_bytes(cipher.encrypt(memory.getvalue()))
        out.chmod(0o600)
        return out


def restore(archive: Path, destination: Path, key: str):
    """Restore ONLY into a fresh directory; source keys/config stay separate."""
    if destination.exists():
        raise ValueError("restore destination must not exist")
    plaintext = Fernet(key.encode()).decrypt(archive.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as bundle:
        member = bundle.getmember("collaboration.sqlite3")
        if not member.isfile():
            raise ValueError("invalid backup")
        contents = bundle.extractfile(member).read()
    destination.mkdir(mode=0o700, parents=True)
    path = destination / "collaboration.sqlite3"
    path.write_bytes(contents)
    path.chmod(0o600)
    with sqlite3.connect(path) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("restored database integrity check failed")
        # A restored gateway must not resend historical chat messages.
        db.execute("UPDATE jobs SET state='done' WHERE kind IN ('decision_card','send','query_reply')")
    store = Store(destination)
    from .projection import export
    export(store)
    return store


def purge_managed_backups(store):
    path = store.root / "backups"
    if path.is_symlink():
        raise ValueError("managed backups must not be a symlink")
    if path.exists():
        for backup_path in path.glob("*.fernet"):
            backup_path.unlink()
    key = os.environ.get("COLLAB_BACKUP_KEY")
    if key:
        backup(store, path, key)
