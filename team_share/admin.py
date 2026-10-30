"""Private-instance operations. No production defaults, no credential logging."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

from .collaboration.config import Member, Settings
from .collaboration.onboarding import atomic_private
from .viewer.auth import Accounts, password_hash


def private_json(path, value):
    atomic_private(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run(args, *, input=None):
    result = subprocess.run(
        [str(x) for x in args],
        input=input,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(
            "Command failed: "
            + Path(str(args[0])).name
            + "; credentials and output withheld"
        )
    return result.stdout


def read_instance(root):
    root = Path(root).expanduser().resolve()
    for name in ("config.json", "instance.json", "viewer.json"):
        p = root / name
        if p.is_symlink() or not p.is_file() or p.stat().st_mode & 0o077:
            raise ValueError("private instance files required")
    return (
        root,
        json.loads((root / "instance.json").read_text()),
        json.loads((root / "config.json").read_text()),
    )


@contextmanager
def instance_lock(root):
    with open(root / ".admin.lock", "a") as stream:
        os.chmod(root / ".admin.lock", 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def save_config(root, data):
    # Validate all changes before replacing the live file.
    Settings(
        data_dir=Path(data["data_dir"]),
        members=tuple(Member(**m) for m in data["members"]),
        config_version=data["config_version"],
    )
    private_json(root / "config.json", data)


def origin(value):
    p = urlsplit(value)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.path
        or p.query
        or p.fragment
        or p.username
        or p.password
        or p.port
    ):
        raise ValueError("Use an HTTPS origin without path or port")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", p.hostname):
        raise ValueError("Use a DNS hostname")
    return value.rstrip("/")


def repo_name(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Use credential-free OWNER/REPO")
    return value


def member_credentials(root, member_id, public_url, *, active=True):
    if not re.fullmatch(r"[a-z0-9_]{1,32}", member_id):
        raise ValueError("invalid member ID")
    values = {"id": member_id, "name": member_id, "open_id": "", "active": active}
    delivery = root / "credentials" / member_id
    delivery.mkdir(parents=True, mode=0o700, exist_ok=True)
    for role in ("publisher", "reader"):
        token = secrets.token_urlsafe(32)
        values["token_hash" if role == "publisher" else "reader_token_hash"] = (
            hashlib.sha256(token.encode()).hexdigest()
        )
        private_json(
            delivery / (role + ".json"), {"url": public_url + "/team", "token": token}
        )
    return values


def initialize(root, members, public_url, repo):
    from .collaboration.__main__ import init

    public_url = origin(public_url)
    repo = repo_name(repo)
    root = Path(root).expanduser().absolute()
    if root.is_symlink() or root.exists():
        raise ValueError("new instance directory required")
    root = root.resolve()
    init(root, members)
    data = json.loads((root / "config.json").read_text())
    data["members"] = [member_credentials(root, m, public_url) for m in members]
    data["confirmation_enabled"] = (
        False  # Opt in only after the two-person workflow is understood.
    )
    data["team_id"] = (
        re.sub(r"[^a-z0-9_-]+", "-", repo.split("/")[1].lower())[:64] or "team"
    )
    save_config(root, data)
    for m in members:
        for role in ("publisher", "reader"):
            (root / f"{m}-{role}.json").unlink()
    (root / "keys").mkdir(mode=0o700)
    (root / "viewer").mkdir(mode=0o700)
    private_json(
        root / "instance.json",
        {
            "instance_version": 1,
            "release": "0.5.0rc1",
            "public_url": public_url,
            "repo": repo,
        },
    )
    private_json(
        root / "viewer.json",
        {
            "public_url": public_url,
            "secure_cookie": True,
            "auth_db": str(root / "viewer/auth.sqlite3"),
            "feishu_db": str(root / "data/collaboration.sqlite3"),
            "git_root": str(root / "mirror/git-cache"),
            "repo": repo,
            "members_config": str(root / "config.json"),
        },
    )
    for m in members:
        Accounts(root / "viewer/auth.sqlite3").create(
            [m], root / "credentials" / m / "web.json"
        )
    return {
        "initialized": True,
        "instance": str(root),
        "credentials": "credentials/<member>/; deliver privately",
        "real_acceptance": "NOT_RUN",
    }


def manage_member(root, command, member_id):
    root, info, data = read_instance(root)
    with instance_lock(root):
        data = json.loads((root / "config.json").read_text())
        rows = data["members"]
        item = next((m for m in rows if m["id"] == member_id), None)
        accounts = Accounts(root / "viewer/auth.sqlite3")
        if command == "member-add":
            if item or len(rows) >= 10:
                raise ValueError(
                    "member exists or 10-member limit reached; IDs are never reused"
                )
            if not re.fullmatch(r"[a-z0-9_]{1,32}", member_id):
                raise ValueError("invalid member ID")
            rows.append(member_credentials(root, member_id, info["public_url"]))
            data["confirmation_enabled"] = False
            accounts.create([member_id], root / "credentials" / member_id / "web.json")
        elif command == "member-disable":
            if not item:
                raise ValueError("unknown member")
            item["active"] = False
            # Invalidate both old token hashes, even if the member is later manually re-enabled.
            for key in ("token_hash", "reader_token_hash"):
                item[key] = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            data["confirmation_enabled"] = False
            save_config(root, data)  # fail closed before session cleanup
            with accounts.connect() as db:
                db.execute("UPDATE users SET active=0 WHERE name=?", (member_id,))
                db.execute("DELETE FROM sessions WHERE username=?", (member_id,))
        elif command == "member-rotate":
            if not item or not item.get("active", True):
                raise ValueError("active member required")
            new = member_credentials(root, member_id, info["public_url"])
            item.update({k: new[k] for k in ("token_hash", "reader_token_hash")})
        elif command == "account-reset":
            if not item or not item.get("active", True):
                raise ValueError("active member required")
            target = (
                root
                / "credentials"
                / member_id
                / ("web-reset-" + secrets.token_hex(6) + ".json")
            )
            password = secrets.token_urlsafe(18)
            salt = secrets.token_hex(16)
            with accounts.connect() as db:
                db.execute(
                    "UPDATE users SET salt=?,hash=? WHERE name=?",
                    (salt, password_hash(password, salt), member_id),
                )
                db.execute("DELETE FROM sessions WHERE username=?", (member_id,))
            private_json(target, {member_id: password})
            return {
                "reset": member_id,
                "private_delivery": str(target),
                "sessions_revoked": True,
            }
        else:
            raise ValueError("unknown member command")
        save_config(root, data)
        return {
            "operation": command,
            "member": member_id,
            "github_access": "administrator must separately revoke/check GitHub access; existing clones retain data",
        }


def connect_git(root, *, create=False):
    root, info, _ = read_instance(root)
    repo = repo_name(info["repo"])
    if create:
        run(["gh", "repo", "create", repo, "--private"])
    meta = json.loads(run(["gh", "api", "repos/" + repo]))
    if not meta.get("private") or not meta.get("permissions", {}).get("admin"):
        raise ValueError("private repository admin access required")
    # Seed only the marker and empty directory, never source configuration or sample business records.
    # GitHub repository.size may lag behind commits; inspect the actual marker.
    marker_check = subprocess.run(
        ["gh", "api", "repos/" + repo + "/contents/.team-memory.yml?ref=main"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if marker_check.returncode and "(HTTP 404)" not in marker_check.stderr:
        raise RuntimeError("Repository marker check failed; no files changed")
    if (
        not marker_check.returncode
        and json.loads(marker_check.stdout).get("type") != "file"
    ):
        raise ValueError("repository marker must be a regular file")
    if marker_check.returncode:
        marker = ".team-memory.yml"
        import base64

        payload = {
            "message": "Initialize private team memory",
            "branch": "main",
            "content": base64.b64encode(
                b'team_name: Shared Team\nversion: "0.1.0"\ntool: team-memory\n'
            ).decode(),
        }
        run(
            [
                "gh",
                "api",
                "--method",
                "PUT",
                "repos/" + repo + "/contents/" + marker,
                "--input",
                "-",
            ],
            input=json.dumps(payload),
        )
    key = root / "keys/github-readonly"
    if key.exists():
        raise ValueError(
            "deploy key already exists; preserved, inspect GitHub key registration before retry"
        )
    run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "team-memory-readonly",
            "-f",
            key,
        ]
    )
    payload = {
        "title": "team-memory-readonly-" + secrets.token_hex(4),
        "key": key.with_suffix(".pub").read_text().strip(),
        "read_only": True,
    }
    run(
        ["gh", "api", "--method", "POST", "repos/" + repo + "/keys", "--input", "-"],
        input=json.dumps(payload),
    )
    keys = json.loads(run(["gh", "api", "meta"]))["ssh_keys"]
    atomic_private(
        root / "keys/github-known-hosts",
        "".join("github.com " + k + "\n" for k in keys),
    )
    return {
        "private_repo_verified": True,
        "readonly_key_registered": True,
        "model_login_copied": False,
    }


def doctor(root, *, online=False):
    root, info, _ = read_instance(root)
    from .collaboration.__main__ import load_secrets

    load_secrets(root / "config.json")
    settings = Settings.load(root / "config.json")
    checks = {
        "configuration": "PASS",
        "active_members": sum(m.active for m in settings.members),
        "feishu_fields": "PASS"
        if settings.chat_id
        and settings.app_id
        and settings.app_secret
        and settings.encrypt_key
        and settings.verification_token
        and all(m.open_id for m in settings.members if m.active)
        else "NOT_CONFIGURED",
        "readonly_git_key": "PASS"
        if (root / "keys/github-readonly").is_file()
        else "NOT_CONFIGURED",
        "mirror_last_success": (root / "mirror/last-sync").read_text().strip()
        if (root / "mirror/last-sync").exists()
        else None,
        "real_two_person_acceptance": "NOT_RUN",
        "model_adapter": "check on designated member computer",
    }
    with Accounts(root / "viewer/auth.sqlite3").connect() as db:
        checks["active_web_accounts"] = db.execute(
            "SELECT count(*) FROM users WHERE active=1"
        ).fetchone()[0]
    archive_db = root / "data/collaboration.sqlite3"
    checks["last_feishu_event"] = None
    checks["pending_jobs"] = None
    if archive_db.is_file():
        with sqlite3.connect(
            archive_db.resolve().as_uri() + "?mode=ro", uri=True
        ) as db:
            checks["last_feishu_event"] = db.execute(
                "SELECT max(created) FROM events WHERE event_id LIKE 'message:%'"
            ).fetchone()[0]
            checks["pending_jobs"] = db.execute(
                "SELECT count(*) FROM jobs WHERE state != 'done'"
            ).fetchone()[0]
    mirror = root / "mirror/git-cache"
    checks["git_read"] = "NOT_CONFIGURED"
    if (mirror / ".git").is_dir():
        try:
            checks["git_commit"] = run(
                ["git", "-C", str(mirror), "rev-parse", "HEAD"]
            ).strip()
            checks["git_read"] = "PASS"
        except RuntimeError:
            checks["git_read"] = "FAIL"
    checks["git_write"] = "check on member computer; server key is read-only"
    if online:
        import httpx

        checks["https"] = "FAIL"
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as c:
                health = c.get(info["public_url"] + "/healthz")
                protected = c.get(info["public_url"] + "/api/memories")
                checks["https"] = (
                    "PASS"
                    if health.status_code == 200
                    and health.json().get("service") == "team-memory-viewer"
                    and protected.status_code == 401
                    else "FAIL"
                )
        except (httpx.HTTPError, ValueError):
            pass
    return checks


def backup_instance(root, destination, key_path):
    root, _, _ = read_instance(root)
    destination = Path(destination).expanduser().absolute()
    key_path = Path(key_path).expanduser().absolute()
    if (
        destination.exists()
        or key_path.exists()
        or destination.is_relative_to(root)
        or key_path.is_relative_to(root)
    ):
        raise ValueError(
            "backup and key require fresh paths outside instance; store separately"
        )
    if destination == key_path:
        raise ValueError("separate key and archive paths required")
    key = Fernet.generate_key()
    payload = io.BytesIO()
    with instance_lock(root), tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        # Explicit allowlist: no Git clone, symlinks, user model credentials or source checkout.
        for name in (
            "config.json",
            "instance.json",
            "viewer.json",
            "secrets.env",
            "credentials",
            "keys",
        ):
            p = root / name
            if not p.exists():
                continue
            if (
                p.is_symlink()
                or p.is_dir()
                and any(x.is_symlink() for x in p.rglob("*"))
            ):
                raise ValueError("symlink in private instance")
            if p.is_dir():
                shutil.copytree(p, stage / name)
            else:
                shutil.copy2(p, stage / name)
        # Canonicalize instance-owned paths while the original filesystem is available.
        # macOS /var -> /private/var aliases must not make portable restores reject their own files.
        for name in ("config.json", "viewer.json"):
            copied = json.loads((stage / name).read_text())
            for field in (
                "data_dir",
                "auth_db",
                "feishu_db",
                "git_root",
                "members_config",
            ):
                if field in copied:
                    resolved = Path(copied[field]).resolve()
                    if not resolved.is_relative_to(root):
                        raise ValueError("backup contains an external instance path")
                    copied[field] = str(resolved)
            private_json(stage / name, copied)
        for relative in ("data/collaboration.sqlite3", "viewer/auth.sqlite3"):
            p = root / relative
            if p.exists():
                if p.is_symlink():
                    raise ValueError("symlink database refused")
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with (
                    sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True) as src,
                    sqlite3.connect(target) as dst,
                ):
                    src.backup(dst)
        (stage / "backup-manifest.json").write_text(
            json.dumps(
                {"version": 1, "original_root": str(root), "real_acceptance": "NOT_RUN"}
            )
        )
        with tarfile.open(fileobj=payload, mode="w:gz") as tar:
            for p in stage.iterdir():
                tar.add(p, arcname=p.name)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path, contents in (
            (key_path, key),
            (destination, Fernet(key).encrypt(payload.getvalue())),
        ):
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(contents)
    return {
        "backup": str(destination),
        "key": str(key_path),
        "encrypted": True,
        "summary_computer_state": "back up separately on member computer",
    }


def restore_instance(archive, destination, key_path):
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("fresh restore destination required")
    plaintext = Fernet(Path(key_path).read_bytes()).decrypt(Path(archive).read_bytes())
    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as tar:
        members = tar.getmembers()
        if any(
            not (m.isfile() or m.isdir())
            or Path(m.name).is_absolute()
            or ".." in Path(m.name).parts
            for m in members
        ):
            raise ValueError("unsafe archive")
        manifest = json.load(tar.extractfile("backup-manifest.json"))
        old = manifest["original_root"]
        destination.mkdir(mode=0o700, parents=True)
        for m in members:
            p = destination / m.name
            if m.isdir():
                p.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                p.write_bytes(tar.extractfile(m).read())
                p.chmod(0o600)
    for name in ("config.json", "viewer.json"):
        data = json.loads((destination / name).read_text())
        for key in ("data_dir", "auth_db", "feishu_db", "git_root", "members_config"):
            if key in data:
                value = Path(data[key])
                base = Path(old)
                if not value.is_relative_to(base):
                    raise ValueError("backup contains external path")
                data[key] = str(destination / value.relative_to(base))
        private_json(destination / name, data)
    for relative in ("data/collaboration.sqlite3", "viewer/auth.sqlite3"):
        p = destination / relative
        if not p.exists():
            continue
        with sqlite3.connect(p) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("database integrity failure")
            if relative.startswith("data/"):
                db.execute(
                    "UPDATE jobs SET state='done' WHERE kind IN ('decision_card','send','query_reply')"
                )
            else:
                db.execute("DELETE FROM sessions")
    Settings.load(destination / "config.json")
    return {
        "restored": str(destination),
        "services_started": False,
        "web_sessions_revoked": True,
        "git_mirror": "rebuild readonly mirror",
        "automatic_message_replay": False,
    }


def render_deploy(root, output, **ports):
    from .deployment import render

    return render(root, output, **ports)


def main():
    p = argparse.ArgumentParser(prog="team-memory-hub-admin")
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("init", "wizard"):
        q = sub.add_parser(command)
        q.add_argument("root", type=Path)
        q.add_argument("--members", nargs="+")
        q.add_argument("--url")
        q.add_argument("--repo")
    for command in ("member-add", "member-disable", "member-rotate", "account-reset"):
        q = sub.add_parser(command)
        q.add_argument("root", type=Path)
        q.add_argument("member")
    for command in (
        "doctor",
        "configure-feishu",
        "connect-git",
        "render-deploy",
        "backup",
        "migrate",
    ):
        q = sub.add_parser(command)
        q.add_argument("root", type=Path)
        if command == "doctor":
            q.add_argument("--online", action="store_true")
        if command == "connect-git":
            q.add_argument("--create", action="store_true")
        if command == "render-deploy":
            q.add_argument("output", type=Path)
            q.add_argument("--archive-port", type=int, default=8791)
            q.add_argument("--viewer-port", type=int, default=8793)
        if command == "backup":
            q.add_argument("archive", type=Path)
            q.add_argument("--key-file", required=True, type=Path)
    q = sub.add_parser("restore")
    q.add_argument("archive", type=Path)
    q.add_argument("destination", type=Path)
    q.add_argument("--key-file", required=True, type=Path)
    args = p.parse_args()
    try:
        if args.command in ("init", "wizard"):
            if args.command == "wizard":
                if not sys.stdin.isatty():
                    raise ValueError("wizard requires interactive terminal")
                args.url = args.url or input("Public HTTPS origin: ").strip()
                args.repo = (
                    args.repo or input("Private data repository OWNER/REPO: ").strip()
                )
                args.members = (
                    args.members
                    or input("Member IDs, space-separated (2–10): ").split()
                )
            if not args.url or not args.repo or not args.members:
                raise ValueError("--url --repo --members required")
            result = initialize(args.root, args.members, args.url, args.repo)
        elif args.command.startswith("member-") or args.command == "account-reset":
            result = manage_member(args.root, args.command, args.member)
        elif args.command == "doctor":
            result = doctor(args.root, online=args.online)
        elif args.command == "connect-git":
            result = connect_git(args.root, create=args.create)
        elif args.command == "render-deploy":
            result = render_deploy(
                args.root,
                args.output,
                archive_port=args.archive_port,
                viewer_port=args.viewer_port,
            )
        elif args.command == "configure-feishu":
            from .collaboration.onboarding import configure_feishu

            configure_feishu(args.root / "config.json")
            result = {"saved": True, "real_acceptance": "NOT_RUN"}
        elif args.command == "backup":
            result = backup_instance(args.root, args.archive, args.key_file)
        elif args.command == "restore":
            result = restore_instance(args.archive, args.destination, args.key_file)
        elif args.command == "migrate":
            # Upgrade only explicit config v1; never mutate on service startup.
            root = args.root
            path = root / "config.json"
            data = json.loads(path.read_text())
            Settings.load(path)
            backup = path.with_name("config.v1.backup.json")
            if data.get("config_version") != 1 or backup.exists():
                raise ValueError("v1 config and unused backup path required")
            atomic_private(backup, path.read_text())
            data["config_version"] = 2
            save_config(root, data)
            result = {
                "config_version": 2,
                "backup": str(backup),
                "production_restarted": False,
            }
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError, RuntimeError, sqlite3.Error):
        print(
            "Operation failed; inspect configuration, permissions and prerequisite checks. Private values withheld.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
