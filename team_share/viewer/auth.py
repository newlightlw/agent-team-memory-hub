from __future__ import annotations
import hashlib
from contextlib import contextmanager
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import string
import time


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


class Accounts:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, salt TEXT NOT NULL, hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, username TEXT NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts(ip TEXT NOT NULL, name TEXT NOT NULL, at REAL NOT NULL);''')
        self.path.chmod(0o600)
        with self.connect() as db:
            if "active" not in {r[1] for r in db.execute("PRAGMA table_info(users)")}:
                db.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        self.dummy_salt = secrets.token_hex(16)
        self.dummy_hash = password_hash("not-a-user", self.dummy_salt)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, names, credentials_path, *, length=16):
        # Never rotate an existing user's long-lived password on redeploy.
        credentials_path = Path(credentials_path)
        if credentials_path.exists():
            raise ValueError("Credential delivery file already exists; no accounts changed")
        if not names or len(set(names)) != len(names) or not all(__import__("re").fullmatch(r"[a-z0-9_]{1,32}", n) for n in names):
            raise ValueError("distinct lowercase member names required")
        if not 16 <= length <= 128:
            raise ValueError("new passwords require at least 16 characters")
        generated = {}
        with self.connect() as db:
            for name in names:
                if db.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
                    raise ValueError("Account already exists; use existing private credentials")
            for name in names:
                while True:
                    password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
                    if any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password) and password not in generated.values():
                        break
                salt = secrets.token_hex(16)
                db.execute('INSERT INTO users(name,salt,hash) VALUES(?,?,?)', (name, salt, password_hash(password, salt)))
                generated[name] = password
            credentials_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            import os
            fd = os.open(credentials_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(generated, stream, indent=2)
        return list(generated)

    def login(self, name, password, ip):
        moment = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE at<?', (moment - 900,))
            db.execute('DELETE FROM sessions WHERE expires<?', (moment,))
            if db.execute('SELECT count(*) FROM attempts WHERE ip=? OR name=?', (ip, name)).fetchone()[0] >= 10:
                return None, 'limited'
            db.execute('INSERT INTO attempts VALUES(?,?,?)', (ip, name, moment))
            row = db.execute('SELECT salt,hash FROM users WHERE name=? AND active=1', (name,)).fetchone()
            good = hmac.compare_digest(password_hash(password, row[0] if row else self.dummy_salt), row[1] if row else self.dummy_hash)
            if not row or not good:
                return None, 'invalid'
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), name, csrf, moment + 14 * 86400))
            db.execute('DELETE FROM attempts WHERE ip=? AND name=?', (ip, name))
        return {'token': token, 'csrf': csrf, 'username': name}, ''

    def session(self, token):
        if not token or len(token) > 200:
            return None
        with self.connect() as db:
            row = db.execute('SELECT username,csrf FROM sessions JOIN users ON users.name=sessions.username WHERE sessions.hash=? AND expires>? AND users.active=1', (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return {'username': row[0], 'csrf': row[1]} if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
