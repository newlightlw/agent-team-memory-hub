import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from rich.console import Console
from team_memory.commands.capture_cmd import capture_cmd
from team_memory.commands.inbox_cmd import propose_cmd
from team_memory.commands.init_cmd import init_cmd
from team_memory.commands.sync_cmd import sync_cmd
from team_memory.config import Config
from team_memory.gitutil import run_git, get_remote_url, is_rebase_in_progress
from team_memory.member_setup import configure_clients
from team_memory.sharing import (
    join,
    SharedReader,
    stage_team_record,
    validate_remote,
    same_remote,
)
from team_memory.store import MemoryStore

QUIET = Console(quiet=True)


def git(path, *args):
    value = run_git(path, *args)
    assert value.returncode == 0, value.stderr
    return value.stdout.strip()


@pytest.fixture
def pair(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
    )
    writer = tmp_path / "writer"
    init_cmd(writer, "Synthetic", "alice", console=QUIET)
    git(writer, "branch", "-M", "main")
    git(writer, "config", "user.name", "Synthetic")
    git(writer, "config", "user.email", "synthetic@localhost")
    git(writer, "remote", "add", "origin", str(remote))
    git(writer, "add", ".")
    git(writer, "commit", "-m", "Initial synthetic data")
    git(writer, "push", "-u", "origin", "main")
    return writer, remote


def test_two_member_fast_forward_and_committed_snapshot(pair, tmp_path):
    writer, remote = pair
    reader = join(str(remote), tmp_path / "reader")
    capture_cmd(
        "Synthetic shared LANTERN",
        "project",
        author="alice",
        root=writer,
        note="explicit selected input",
        console=QUIET,
    )
    git(writer, "add", ".")
    git(writer, "commit", "-m", "Share synthetic source")
    git(writer, "push")
    assert sync_cmd(reader, push=False, console=QUIET)
    result = SharedReader(reader, auto_sync=False).snapshot()
    assert result["commit"] == git(writer, "rev-parse", "HEAD")
    assert any(x["title"] == "Synthetic shared LANTERN" for x in result["records"])
    # A local worktree edit must never replace committed knowledge in MCP output.
    path = next((reader / "memory/project").glob("mem-*.md"))
    path.write_text("uncommitted tampering")
    assert not sync_cmd(reader, push=False, console=QUIET)
    assert path.read_text() == "uncommitted tampering"
    assert any(
        x["title"] == "Synthetic shared LANTERN"
        for x in SharedReader(reader, auto_sync=False).snapshot()["records"]
    )
    with pytest.raises(ValueError, match="read-only"):
        MemoryStore(reader).save_entry(MemoryStore(writer).list_entries()[0])
    with pytest.raises(ValueError, match="read-only"):
        sync_cmd(reader, console=QUIET)
    assert get_remote_url(reader) == str(remote)


def test_join_never_replaces_another_checkout_or_repo(pair, tmp_path):
    writer, remote = pair
    with pytest.raises(ValueError, match="writer"):
        join(str(remote), writer)
    root = tmp_path / "existing"
    root.mkdir()
    (root / "mine").write_text("keep")
    with pytest.raises(ValueError):
        join(str(remote), root)
    assert (root / "mine").read_text() == "keep"
    root = join(str(remote), tmp_path / "reader")
    assert join(str(remote), root) == root
    with pytest.raises(ValueError):
        join(str(remote), root, branch="other")


def test_failure_or_divergence_never_authorizes_push(pair, tmp_path):
    writer, remote = pair
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    git(other, "config", "user.name", "Other")
    git(other, "config", "user.email", "other@localhost")
    (other / "remote-only").write_text("remote")
    git(other, "add", ".")
    git(other, "commit", "-m", "Remote changed")
    git(other, "push")
    (writer / "local-only").write_text("preserve")
    git(writer, "add", ".")
    git(writer, "commit", "-m", "Local changed")
    remote_head = git(other, "rev-parse", "HEAD")
    local_head = git(writer, "rev-parse", "HEAD")
    assert not sync_cmd(writer, console=QUIET)
    assert git(writer, "rev-parse", "HEAD") == local_head
    assert (
        git(other, "ls-remote", "origin", "refs/heads/main").split()[0] == remote_head
    )
    (writer / ".git/rebase-merge").mkdir()
    assert is_rebase_in_progress(writer)
    assert not sync_cmd(writer, console=QUIET)


def test_pending_ids_do_not_collide(pair):
    writer, _ = pair
    a = propose_cmd(
        "Pending one", "project", author="alice", root=writer, console=QUIET
    )
    b = propose_cmd(
        "Pending two", "project", author="alice", root=writer, console=QUIET
    )
    assert a != b and a.exists() and b.exists()
    assert len(MemoryStore(writer).list_inbox()) == 2


def test_token_urls_rejected_and_remote_alias_supported(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        validate_remote("https://user:synthetic@example.invalid/repo")
    with pytest.raises(ValueError):
        Config(
            gitea_remote_url="https://example.invalid/repo", gitea_token="synthetic"
        ).resolved_remote_url()
    monkeypatch.setenv("REMOTE_URL", "https://github.com/example/team.git")
    cfg = Config.from_env(tmp_path / "none")
    assert cfg.resolved_remote_url() == "https://github.com/example/team.git"
    assert same_remote(
        "git@github.com:example/team.git", "https://github.com/example/team"
    )


def test_client_merge_preserves_other_mcp_and_is_idempotent(tmp_path):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".hermes").mkdir()
    codex = home / ".codex/config.toml"
    codex.write_text('# user comment\n[mcp_servers.other]\ncommand="other"\n')
    claude = home / ".claude.json"
    claude.write_text('{"unrelated":42,"mcpServers":{"other":{"command":"other"}}}')
    hermes = home / ".hermes/config.yaml"
    hermes.write_text(
        "# keep comment\nmodel: synthetic\nmcp_servers:\n  other: {command: other}\n"
    )
    result = configure_clients(
        tmp_path / "reader",
        Path("/synthetic/python"),
        ["codex", "claude", "hermes"],
        home=home,
        author="alice",
    )
    texts = [p.read_text() for p in (codex, claude, hermes)]
    assert "other" in texts[0] and "# user comment" in texts[0]
    assert json.loads(texts[1])["unrelated"] == 42
    assert "# keep comment" in texts[2] and "other" in texts[2]
    assert all(
        p.stat().st_mode & 0o777 == 0o600
        for p in Path(result["backup_directory"]).iterdir()
    )
    assert (
        configure_clients(
            tmp_path / "reader",
            Path("/synthetic/python"),
            ["codex", "claude", "hermes"],
            home=home,
            author="alice",
        )["configured"]
        == []
    )
    assert texts == [p.read_text() for p in (codex, claude, hermes)]


def test_client_conflict_preflight_leaves_all_configs_unchanged(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    path = home / ".claude.json"
    path.write_text('{"mcpServers":{"team_memory_hub":{"command":"existing"}}}')
    with pytest.raises(ValueError, match="Existing"):
        configure_clients(
            tmp_path / "reader",
            Path("/synthetic/python"),
            ["codex", "claude"],
            home=home,
        )
    assert not (home / ".codex/config.toml").exists()
    assert (
        json.loads(path.read_text())["mcpServers"]["team_memory_hub"]["command"]
        == "existing"
    )


def test_explicit_service_source_stages_locally_with_provenance(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            assert self.headers["Authorization"] == "Bearer synthetic-reader"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "id": "mem-20261030-demo-001",
                        "title": "Synthetic source",
                        "body": "LANTERN",
                        "author": "demo",
                        "status": "active",
                        "kind": "share",
                        "revision": 2,
                    }
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        credentials = tmp_path / "reader.json"
        credentials.write_text(
            json.dumps(
                {
                    "url": "http://127.0.0.1:" + str(server.server_port),
                    "token": "synthetic-reader",
                }
            )
        )
        credentials.chmod(0o600)
        out = stage_team_record(
            "mem-20261030-demo-001",
            credentials,
            tmp_path / "outbox",
            "alice",
            "project",
        )
        data = json.loads(out.read_text())
        assert data["uploaded"] is False and data["status"] == "pending_review"
        assert (
            data["provenance"]["author"] == "demo"
            and data["provenance"]["revision"] == 2
        )
        assert data["provenance"]["record_kind"] == "share"
        assert requests == ["/api/records/mem-20261030-demo-001"]
        assert out.stat().st_mode & 0o777 == 0o600
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_stdio_mcp_has_no_approval_or_upload(pair, tmp_path):
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    writer, remote = pair
    root = join(str(remote), tmp_path / "reader")

    async def probe():
        args = StdioServerParameters(
            command=sys.executable,
            args=["-m", "team_memory.shared_mcp"],
            env={
                **os.environ,
                "TEAM_MEMORY_ROOT": str(root),
                "TEAM_MEMORY_AUTO_SYNC": "0",
                "TEAM_MEMORY_OUTBOX": str(tmp_path / "outbox"),
                "TEAM_MEMORY_AUTHOR": "alice",
            },
        )
        async with stdio_client(args) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
                names = {t.name for t in tools.tools}
                assert names == {
                    "search_shared_memory",
                    "get_shared_memory",
                    "list_shared_memory",
                    "prepare_shared_memory",
                }
                value = await client.call_tool("list_shared_memory", {})
                data = json.loads(value.content[0].text)
                assert (
                    data["commit"] == git(writer, "rev-parse", "HEAD")
                    and data["stale"] is False
                )
                proposed = await client.call_tool(
                    "prepare_shared_memory",
                    {
                        "title": "Synthetic local draft",
                        "body": "Explicitly selected synthetic material",
                    },
                )
                assert json.loads(proposed.content[0].text)["uploaded"] is False
                assert not git(root, "status", "--porcelain")

    asyncio.run(probe())


def test_shared_reader_reports_stale_without_erasing_cache(pair, tmp_path):
    writer, remote = pair
    root = join(str(remote), tmp_path / "reader")
    previous = git(root, "rev-parse", "HEAD")
    remote.rename(tmp_path / "temporarily-unavailable.git")
    result = SharedReader(root, auto_sync=True).snapshot()
    assert (
        result["stale"] is True
        and result["commit"] == previous
        and result["sync_error"]
    )
    assert not git(root, "status", "--porcelain")


def test_source_draft_submit_requires_human_terminal(pair, tmp_path, monkeypatch):
    from team_memory.sharing import submit_draft, stage_draft

    writer, _ = pair
    draft = stage_draft(
        "Synthetic local material",
        "Chosen material",
        "project",
        "alice",
        tmp_path / "outbox",
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="interactive"):
        submit_draft(draft, writer)
    assert not MemoryStore(writer).list_inbox()


def test_source_change_refuses_before_human_upload(pair, tmp_path, monkeypatch):
    import team_memory.sharing as sharing

    writer, _ = pair
    draft = sharing.stage_draft(
        "Synthetic source",
        "Original",
        "project",
        "alice",
        tmp_path / "outbox",
        provenance={
            "id": "mem-20261030-demo-001",
            "requires_source_recheck": True,
            "revision": 1,
            "source_digest": "old",
        },
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        sharing,
        "fetch_team_record",
        lambda *args: {"title": "Synthetic source", "body": "Changed", "revision": 2},
    )
    with pytest.raises(ValueError, match="Source changed"):
        sharing.submit_draft(draft, writer, reader=tmp_path / "reader.json")
    assert not MemoryStore(writer).list_inbox()


def test_reader_origin_is_not_changed_by_legacy_global_environment(
    pair, tmp_path, monkeypatch
):
    _, remote = pair
    root = join(str(remote), tmp_path / "reader")
    monkeypatch.setenv("REMOTE_URL", "https://github.com/example/unrelated.git")
    monkeypatch.setenv("GITEA_TOKEN", "synthetic-unused-legacy-value")
    assert sync_cmd(root, push=False, console=QUIET)
    assert get_remote_url(root) == str(remote)


def test_first_refresh_runs_even_on_a_freshly_booted_machine(
    pair, tmp_path, monkeypatch
):
    import team_memory.sharing as sharing

    _, remote = pair
    root = join(str(remote), tmp_path / "reader")
    remote.rename(tmp_path / "unavailable.git")
    monkeypatch.setattr(sharing.time, "monotonic", lambda: 1.0)
    reader = SharedReader(root, auto_sync=True)
    first = reader.snapshot()
    assert first["stale"] is True and reader.last_attempt == 1.0
    assert first["sync_error"]
