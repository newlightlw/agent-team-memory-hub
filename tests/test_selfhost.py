import hashlib
import json
import socket
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from team_share.admin import (
    backup_instance,
    doctor,
    initialize,
    manage_member,
    restore_instance,
)
from team_share.collaboration.api import create_app
from team_share.collaboration.config import Member, Settings
from team_share.collaboration.store import Store
from team_share.viewer.app import create_app as viewer
from team_share.viewer.auth import Accounts, password_hash


def instance(tmp_path, n=2):
    root = tmp_path / "instance"
    initialize(
        root,
        [f"member{i}" for i in range(n)],
        "https://memory.example.com",
        "example/private-memory",
    )
    return root


def credential(root, name, role):
    return json.loads((root / "credentials" / name / (role + ".json")).read_text())


def test_ten_members_validation_and_no_default_accounts(tmp_path):
    root = instance(tmp_path, 10)
    s = Settings.load(root / "config.json")
    assert len(s.members) == 10 and s.config_version == 2
    with Accounts(root / "viewer/auth.sqlite3").connect() as db:
        assert {r[0] for r in db.execute("SELECT name FROM users")} == {
            f"member{i}" for i in range(10)
        }
    assert all(
        len(next(iter(credential(root, m.id, "web").values()))) >= 16 for m in s.members
    )
    assert not (root / "vayne-reader.json").exists()
    with pytest.raises(ValueError):
        replace(s, members=(s.members[0],) * 2)
    with pytest.raises(ValueError):
        replace(
            s,
            members=s.members
            + (
                Member(
                    "extra",
                    "x",
                    "",
                    hashlib.sha256(b"x").hexdigest(),
                    hashlib.sha256(b"y").hexdigest(),
                ),
            ),
        )
    with pytest.raises(ValueError):
        manage_member(root, "member-add", "extra")


def test_live_disable_revokes_service_session_feishu_and_does_not_change_authors(
    tmp_path,
):
    root = instance(tmp_path)
    data = json.loads((root / "config.json").read_text())
    data["members"][0]["open_id"] = "ou_first"
    from team_share.admin import save_config

    save_config(root, data)
    cfg = json.loads((root / "viewer.json").read_text())
    api = create_app(Settings.load(root / "config.json"), run_worker=False)
    with (
        TestClient(api) as c,
        TestClient(viewer(cfg), base_url="https://memory.example.com") as web,
    ):
        auth = {
            "Authorization": "Bearer " + credential(root, "member0", "reader")["token"]
        }
        pub = {
            "Authorization": "Bearer "
            + credential(root, "member0", "publisher")["token"]
        }
        r = c.post(
            "/api/records", headers=pub, json={"title": "shared", "body": "evidence"}
        )
        assert r.status_code == 201
        record_id = r.json()["id"]
        password = credential(root, "member0", "web")["member0"]
        assert (
            web.post(
                "/api/login",
                headers={"Origin": "https://memory.example.com"},
                json={"username": "member0", "password": password},
            ).status_code
            == 200
        )
        assert web.get("/api/me").status_code == 200
        assert c.get("/api/me", headers=auth).status_code == 200
        manage_member(root, "member-disable", "member0")
        assert c.get("/api/me", headers=auth).status_code == 401
        assert (
            c.post(
                "/api/records", headers=pub, json={"title": "x", "body": "x"}
            ).status_code
            == 401
        )
        assert web.get("/api/me").status_code == 401
        assert (
            web.post(
                "/api/login",
                headers={"Origin": "https://memory.example.com"},
                json={"username": "member0", "password": password},
            ).status_code
            == 401
        )
        other = {
            "Authorization": "Bearer " + credential(root, "member1", "reader")["token"]
        }
        assert (
            c.get("/api/records/" + record_id, headers=other).json()["author"]
            == "member0"
        )
        with pytest.raises(PermissionError):
            Settings.load(root / "config.json").feishu_member("ou_first")


def test_add_rotate_reset_and_consensus_gate(tmp_path):
    root = instance(tmp_path)
    manage_member(root, "member-add", "third")
    s = Settings.load(root / "config.json")
    assert len(s.members) == 3
    token = credential(root, "third", "reader")["token"]
    assert s.identify(token)
    manage_member(root, "member-rotate", "third")
    assert Settings.load(root / "config.json").identify(token) is None
    account = Accounts(root / "viewer/auth.sqlite3")
    password = credential(root, "third", "web")["third"]
    login, _ = account.login("third", password, "synthetic-ip")
    assert account.session(login["token"])
    result = manage_member(root, "account-reset", "third")
    assert account.session(login["token"]) is None
    assert account.login("third", password, "synthetic-ip")[0] is None
    new = json.loads(Path(result["private_delivery"]).read_text())["third"]
    assert account.login("third", new, "synthetic-ip")[0]
    from team_share.collaboration.service import Collaboration

    service = Collaboration(Settings.load(root / "config.json"))
    with pytest.raises(ValueError, match="two-person"):
        service.create(
            service.settings.members[0], {"kind": "decision", "title": "x", "body": "x"}
        )


def test_full_encrypted_backup_restore_preserves_accounts_records_and_drops_sessions(
    tmp_path,
):
    root = instance(tmp_path)
    store = Store(root / "data")
    with store.transaction() as db:
        item = store.create(
            db, kind="share", author="member0", title="synthetic", body="evidence"
        )
        store.enqueue(db, "query_reply", item["id"])
    password = credential(root, "member0", "web")["member0"]
    accounts = Accounts(root / "viewer/auth.sqlite3")
    login, _ = accounts.login("member0", password, "local")
    assert login
    before = {p.name: p.read_bytes() for p in root.glob("*.json")}
    archive = tmp_path / "backups/snapshot.fernet"
    key = tmp_path / "keys/recovery.key"
    backup_instance(root, archive, key)
    assert b"evidence" not in archive.read_bytes()
    target = tmp_path / "restored"
    result = restore_instance(archive, target, key)
    assert result["services_started"] is False
    assert Store(target / "data").get(item["id"])["body"] == "evidence"
    assert all(
        j["state"] == "done"
        for j in Store(target / "data").jobs()
        if j["kind"] == "query_reply"
    )
    restored = Accounts(target / "viewer/auth.sqlite3")
    assert restored.session(login["token"]) is None
    assert restored.login("member0", password, "local")[0]
    assert Settings.load(target / "config.json").data_dir == target / "data"
    assert json.loads((target / "viewer.json").read_text())["members_config"] == str(
        target / "config.json"
    )
    assert before == {p.name: p.read_bytes() for p in root.glob("*.json")}
    with pytest.raises(ValueError):
        restore_instance(archive, target, key)
    with pytest.raises(ValueError):
        backup_instance(root, root / "bad", tmp_path / "another.key")


def test_legacy_web_password_survives_schema_upgrade(tmp_path):
    p = tmp_path / "old.sqlite3"
    salt = "00" * 16
    with sqlite3.connect(p) as db:
        db.execute("CREATE TABLE users(name TEXT PRIMARY KEY,salt TEXT,hash TEXT)")
        db.execute(
            "INSERT INTO users VALUES(?,?,?)",
            ("alice", salt, password_hash("Old12345", salt)),
        )
    accounts = Accounts(p)
    assert accounts.login("alice", "Old12345", "local")[0]


def test_render_is_reviewable_generic_and_no_host_mutation(tmp_path, monkeypatch):
    root = instance(tmp_path)
    from team_share.deployment import render

    monkeypatch.setattr("getpass.getuser", lambda: "memory")
    ports = []
    for _ in range(2):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
    result = render(
        root, tmp_path / "deploy", archive_port=ports[0], viewer_port=ports[1]
    )
    assert not result["applied"]
    script = tmp_path / "deploy/activate.sh"
    assert (
        subprocess.run(
            ["bash", "-n", script], check=False, capture_output=True
        ).returncode
        == 0
    )
    config = (tmp_path / "deploy/https.conf").read_text()
    assert "location /team/" in config and "memory.example.com" in config
    assert str(ports[0]) in config and str(ports[1]) in config
    assert "manisfast" not in config
    assert doctor(root)["real_two_person_acceptance"] == "NOT_RUN"


def test_claude_rejects_unsafe_cli_and_audits_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from team_memory.claude_summarizer import REQUIRED, probe, summarize

    binary = tmp_path / "claude"
    schema = {
        k: "synthetic evidence"
        for k in (
            "purpose",
            "process",
            "results",
            "insights",
            "applications",
            "discussions",
        )
    }

    def fake(tools):
        binary.write_text(
            "#!"
            + sys.executable
            + '\nimport sys,json\nif "--help" in sys.argv: print('
            + repr(" ".join(REQUIRED))
            + ");sys.exit(0)\nsys.stdin.read()\nprint(json.dumps("
            + repr(
                {"type": "system", "subtype": "init", "tools": tools, "mcp_servers": []}
            )
            + "))\nprint(json.dumps("
            + repr(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "structured_output": schema,
                }
            )
            + "))\n"
        )
        binary.chmod(0o700)

    binary.write_text("#!" + sys.executable + '\nprint("old CLI")\n')
    binary.chmod(0o700)
    with pytest.raises(RuntimeError, match="safety"):
        probe(str(binary))
    fake([])
    assert summarize({"body": "synthetic"}, str(binary)) == schema
    fake(["Bash"])
    with pytest.raises(RuntimeError, match="active"):
        summarize({"body": "synthetic"}, str(binary))


def test_v1_settings_still_read_and_invalid_identity_fails(tmp_path):
    root = instance(tmp_path)
    data = json.loads((root / "config.json").read_text())
    data["config_version"] = 1
    for m in data["members"]:
        m.pop("active")
    (root / "config.json").write_text(json.dumps(data))
    assert Settings.load(root / "config.json").config_version == 1
    data["members"][1]["open_id"] = data["members"][0]["open_id"] = "ou_same"
    (root / "config.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="identities"):
        Settings.load(root / "config.json")


def test_backup_restore_handles_parent_directory_alias(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    root = alias / "instance"
    initialize(
        root, ["alice", "bob"], "https://memory.example.com", "example/private-memory"
    )
    assert Settings.load(root / "config.json").data_dir == real / "instance/data"
    archive = tmp_path / "backup.fernet"
    key = tmp_path / "key"
    backup_instance(root, archive, key)
    restored = tmp_path / "restored"
    restore_instance(archive, restored, key)
    assert Settings.load(restored / "config.json").data_dir == restored / "data"


def test_feishu_wizard_skips_disabled_unbound_members(tmp_path, monkeypatch):
    root = instance(tmp_path)
    manage_member(root, "member-disable", "member0")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["cli_test", "oc_test", "", "ou_active"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _: "synthetic-local-secret")
    from team_share.collaboration.onboarding import configure_feishu

    configure_feishu(root / "config.json")
    settings = Settings.load(root / "config.json")
    assert settings.members[0].open_id == "" and not settings.members[0].active
    assert settings.members[1].open_id == "ou_active"
