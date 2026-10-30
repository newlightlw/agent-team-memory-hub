import base64
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from team_memory.archive import GitHubArchive, archive_selected, FIELDS, render_archive, validate_summary
from team_memory.archive_sync import FeishuArchiveSync
from team_memory.models import parse_memory
from team_memory.member_setup import configure_clients

SUMMARY = {k: "未提及" for k in FIELDS}


class FakeGitHub(GitHubArchive):
    def __init__(self, **kwargs):
        super().__init__("example/private", enabled=True, **kwargs)
        self.files = {}
        self.private = True
        self.timeout_after_write = False
        self.puts = 0

    def api(self, path, *, method="GET", payload=None, missing_ok=False):
        if path == "repos/" + self.repo:
            return {"private": self.private}
        path = path.split("?")[0]
        if method == "GET":
            return self.files.get(path)
        self.puts += 1
        old = self.files.get(path)
        assert (payload.get("sha") if payload else None) == (old["sha"] if old else None)
        result = {"content": payload["content"], "sha": str(self.puts), "html_url": "https://example/record"}
        self.files[path] = result
        if self.timeout_after_write:
            self.timeout_after_write = False
            raise RuntimeError("accepted, response lost")
        return {"content": result, "commit": {"sha": "commit-" + str(self.puts)}}


def test_summary_complete_and_evidence_preserved():
    with pytest.raises(ValueError):
        validate_summary({"purpose": "brief"})
    with pytest.raises(ValueError):
        validate_summary({**SUMMARY, "process": ""})
    body = render_archive("Test", SUMMARY, author="alice", source="codex", source_refs=["chat:123"], original="verbatim source")
    assert "verbatim source" in body and "chat:123" in body
    assert all(heading in body for heading in FIELDS.values())
    assert "不代表团队共识" in body


def test_private_gate_idempotency_unknown_result_and_withdrawal():
    writer = FakeGitHub()
    args = dict(request_id="stable", title="Summary", body="source data", author="alice", source="codex", date="2026-10-30")
    writer.private = False
    with pytest.raises(ValueError, match="PRIVATE"):
        writer.publish(**args)
    assert not writer.files
    writer.private = True
    writer.timeout_after_write = True
    result = writer.publish(**args)
    assert result["uploaded"] and result["duplicate"] and writer.puts == 1
    assert writer.publish(**args)["duplicate"]
    args.update(title="已撤回", body="withdrawn", deprecated=True)
    assert writer.publish(**args)["uploaded"]
    record = parse_memory(base64.b64decode(next(iter(writer.files.values()))["content"]).decode())
    assert record.status == "deprecated" and "source data" not in record.body
    with pytest.raises(ValueError, match="another author"):
        writer.publish(**{**args, "author": "bob"})


def test_disabled_and_durable_local_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAM_MEMORY_OUTBOX", str(tmp_path))
    args = dict(title="Selected", summary=SUMMARY, source_refs=["chat:abc"], request_id="same", source="codex", author="alice")
    writer = Mock()
    writer.publish.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        archive_selected(**args, writer=writer)
    draft = next(tmp_path.glob("archive-*.json"))
    assert json.loads(draft.read_text())["uploaded"] is False
    assert draft.stat().st_mode & 0o077 == 0
    writer.publish.side_effect = None
    writer.publish.return_value = {"uploaded": True}
    assert archive_selected(**args, writer=writer)["uploaded"]
    with pytest.raises(ValueError, match="reused"):
        archive_selected(**{**args, "title": "other"}, writer=writer)
    with pytest.raises(ValueError, match="disabled"):
        GitHubArchive("example/private").publish(request_id="x", title="x", body="x", author="alice", source="codex")


def sample_record():
    return dict(id="mem-20261030-alice-001", author="alice", title="Source", body="full raw source",
                status="active", revision=1, updated="2026-10-30T12:00", created="2026-10-30T12:00", source_url="feishu:message:synthetic")


def test_feishu_summary_before_upload_and_withdrawal(tmp_path):
    rec = sample_record()
    writer = Mock()
    writer.publish.return_value = {"uploaded": True}
    summary = Mock(return_value=SUMMARY)
    worker = FeishuArchiveSync({"state": str(tmp_path / "state.json"), "team_id": "test"}, writer=writer, summarize=summary)
    worker.request = Mock(side_effect=[{"records": [rec], "next_cursor": "one"}, rec])
    assert worker.tick() == 1
    summary.assert_called_once_with(rec)
    assert "full raw source" in writer.publish.call_args.kwargs["body"]
    assert worker.state["cursor"] == "one"
    withdrawn = {**rec, "status": "withdrawn", "body": "", "updated": "2026-10-30T13:00"}
    worker.request = Mock(return_value={"records": [withdrawn], "next_cursor": "two"})
    assert worker.tick() == 1
    assert writer.publish.call_args.kwargs["deprecated"] is True
    assert "full raw source" not in writer.publish.call_args.kwargs["body"]
    assert summary.call_count == 1


def test_feishu_failed_summary_or_changed_source_does_not_advance(tmp_path):
    rec = sample_record()
    writer = Mock()
    worker = FeishuArchiveSync({"state": str(tmp_path / "state.json"), "team_id": "test"}, writer=writer,
                              summarize=Mock(side_effect=RuntimeError("model unavailable")))
    worker.request = Mock(return_value={"records": [rec], "next_cursor": "bad"})
    with pytest.raises(RuntimeError):
        worker.tick()
    assert worker.state["cursor"] == ""
    writer.publish.assert_not_called()
    worker.summarize = Mock(return_value=SUMMARY)
    worker.request = Mock(side_effect=[{"records": [rec], "next_cursor": "bad"}, {**rec, "status": "withdrawn"}])
    with pytest.raises(RuntimeError, match="changed"):
        worker.tick()
    writer.publish.assert_not_called()


@pytest.mark.parametrize("tool", ["codex", "claude", "hermes"])
def test_member_upload_upgrade_preserves_other_clients(tmp_path, monkeypatch, tool):
    monkeypatch.setattr("shutil.which", lambda _: "/synthetic/gh")
    home = tmp_path / "home"
    root = tmp_path / "cache"
    path = home / {"codex": ".codex/config.toml", "claude": ".claude.json", "hermes": ".hermes/config.yaml"}[tool]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text({"codex": 'model = "test"\n[mcp_servers.unrelated]\ncommand = "keep"\n',
                     "claude": '{"model":"test","mcpServers":{"unrelated":{"command":"keep"}}}',
                     "hermes": 'model: test\n# keep this comment\nmcp_servers:\n  unrelated:\n    command: keep\nother_setting: keep\n'}[tool])
    old = home / ".local/share/team-memory-hub/releases/v0.3.1/venv/bin/python"
    new = home / ".local/share/team-memory-hub/releases/v0.4.0/venv/bin/python"
    configure_clients(root, old, [tool], home=home, author="alice")
    configure_clients(root, new, [tool], home=home, author="alice", upload_repo="example/private")
    import tomllib
    import yaml
    raw = path.read_text()
    config = tomllib.loads(raw) if tool == "codex" else json.loads(raw) if tool == "claude" else yaml.safe_load(raw)
    servers = config["mcpServers" if tool == "claude" else "mcp_servers"]
    assert config["model"] == "test" and servers["unrelated"]["command"] == "keep"
    assert servers["team_memory_hub"]["env"]["TEAM_MEMORY_UPLOAD_ENABLED"] == "1"
    assert servers["team_memory_hub"]["command"] == str(new)
    if tool == "hermes":
        assert raw.count("  team_memory_hub:") == 1
        assert "# keep this comment" in raw and config["other_setting"] == "keep"
    directory = {"codex": ".codex", "claude": ".claude", "hermes": ".hermes"}[tool]
    assert (home / directory / "skills/team-memory-hub-archive/SKILL.md").is_file()
    assert not configure_clients(root, new, [tool], home=home, author="alice", upload_repo="example/private")["configured"]


def test_literal_credentials_removed_before_github():
    from team_memory.archive import redact_credentials
    token = "ghp_" + "a" * 30
    text = "context " + token + " api_key=" + "b" * 30 + " keep result LANTERN"
    safe = redact_credentials(text)
    assert token not in safe and "b" * 30 not in safe
    assert "keep result LANTERN" in safe
    writer = FakeGitHub()
    writer.publish(request_id="safe", title="safe", body=text, author="alice", source="codex")
    raw = base64.b64decode(next(iter(writer.files.values()))["content"]).decode()
    assert token not in raw and "b" * 30 not in raw


def test_multibyte_archive_cannot_exceed_reader_blob_budget():
    with pytest.raises(ValueError, match="blob budget"):
        render_archive("large", SUMMARY, author="alice", source="codex", source_refs=["synthetic:test"], original="中" * 90000)


@pytest.mark.skipif(__import__('os').name == 'nt', reason='POSIX background process-group acceptance')
@pytest.mark.parametrize('parent_exits', [False, True])
@pytest.mark.parametrize('adapter', ['codex', 'claude'])
def test_summary_timeout_kills_cli_descendants_and_removes_auth_copy(tmp_path, monkeypatch, parent_exits, adapter):
    import os
    import subprocess
    import sys
    import tempfile
    import importlib
    module = importlib.import_module("team_memory.archive_summarizer" if adapter == "codex" else "team_memory.claude_summarizer")
    summarize = module.summarize
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(module, "probe", lambda _: {})
    pid_file = tmp_path / 'synthetic-child.pid'
    binary = tmp_path / 'fake-codex'
    binary.write_text('#!' + sys.executable + '\n' +
        'import subprocess,sys,time,pathlib\n' +
        'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(120)"])\n' +
        'pathlib.Path(' + repr(str(pid_file)) + ').write_text(str(child.pid))\n' +
        ('sys.exit(0)\n' if parent_exits else 'time.sleep(120)\n'))
    binary.chmod(0o700)
    auth = tmp_path / 'synthetic-auth.json'
    auth.write_text('{"synthetic":"not-a-real-credential"}')
    # Synchronize startup separately: this test verifies descendant cleanup,
    # not whether an interpreter starts within one second on a loaded CI runner.
    import time
    native_popen = subprocess.Popen
    def spawn_ready(*args, **kwargs):
        process = native_popen(*args, **kwargs)
        deadline = time.monotonic() + 10
        while not pid_file.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not pid_file.exists():
            try:
                os.killpg(process.pid, __import__('signal').SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            pytest.fail('synthetic CLI failed its readiness handshake')
        return process
    native_killpg = os.killpg
    killed = []
    def terminate_once(pid, sig):
        killed.append(pid)
        return native_killpg(pid, sig)
    with monkeypatch.context() as scoped:
        scoped.setattr(module.subprocess, 'Popen', spawn_ready)
        scoped.setattr(os, 'killpg', terminate_once)
        with pytest.raises(RuntimeError, match='timed out|timeout'):
            kwargs = {'auth_file':str(auth)} if adapter == 'codex' else {}
            summarize({'body':'synthetic'}, str(binary), timeout=1, **kwargs)
    assert len(killed) == 1  # Never signal the same already-reaped process group twice.
    assert pid_file.exists()
    pid = int(pid_file.read_text())
    result = subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True)
    assert result.returncode != 0 or result.stdout.strip().startswith('Z')
    assert not list(tmp_path.glob('team-memory-summary-*/auth.json'))
    assert not list(tmp_path.glob('team-memory-claude-summary-*'))


def test_hermes_upgrade_repairs_owned_legacy_duplicate_keys(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setattr('shutil.which', lambda _: '/synthetic/gh')
    home = tmp_path / 'home'
    root = tmp_path / 'cache'
    old = home / '.local/share/team-memory-hub/releases/v0.3.1/venv/bin/python'
    new = home / '.local/share/team-memory-hub/releases/v0.4.2/venv/bin/python'
    configure_clients(root, old, ['hermes'], home=home, author='alice')
    path = home / '.hermes/config.yaml'
    raw = path.read_text()
    owned_line = next(line for line in raw.splitlines(keepends=True) if line.startswith('  team_memory_hub:'))
    path.write_text(raw.replace('mcp_servers:\n', 'mcp_servers:\n' + owned_line))
    configure_clients(root, new, ['hermes'], home=home, author='alice', upload_repo='example/private')
    raw = path.read_text()
    assert raw.count('  team_memory_hub:') == 1
    assert yaml.safe_load(raw)['mcp_servers']['team_memory_hub']['command'] == str(new)
