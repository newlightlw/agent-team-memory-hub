import json
import tomllib
from pathlib import Path

import pytest
import yaml

from team_memory.member_setup import configure_clients


@pytest.mark.parametrize("tool", ["codex", "claude", "hermes"])
def test_hub_install_preserves_stable_mcp_and_custom_skill(tmp_path, monkeypatch, tool):
    monkeypatch.setattr("shutil.which", lambda _: "/synthetic/gh")
    home = tmp_path / "home"
    name = {
        "codex": ".codex/config.toml",
        "claude": ".claude.json",
        "hermes": ".hermes/config.yaml",
    }[tool]
    path = home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    stable = {
        "command": "/existing/v0.4.2/python",
        "args": ["-m", "team_memory.shared_mcp"],
        "env": {
            "TEAM_MEMORY_ROOT": "/existing/private-memory",
            "TEAM_MEMORY_AUTHOR": "alice",
        },
    }
    if tool == "codex":
        path.write_text(
            '[mcp_servers.team_memory_github]\ncommand="/existing/v0.4.2/python"\nargs=["-m","team_memory.shared_mcp"]\n[mcp_servers.team_memory_github.env]\nTEAM_MEMORY_ROOT="/existing/private-memory"\nTEAM_MEMORY_AUTHOR="alice"\n'
        )
    elif tool == "claude":
        path.write_text(json.dumps({"mcpServers": {"team_memory_github": stable}}))
    else:
        path.write_text(yaml.safe_dump({"mcp_servers": {"team_memory_github": stable}}))
    folder = (
        home
        / {"codex": ".codex", "claude": ".claude", "hermes": ".hermes"}[tool]
        / "skills/team-memory-archive"
    )
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("existing customized stable skill")
    root = home / ".local/share/team-memory-hub/cache"
    configure_clients(
        root,
        home
        / ".local/share/team-memory-hub/releases/v0.5.0-candidate.1/venv/bin/python",
        [tool],
        home=home,
        author="alice",
        upload_repo="example/private-hub",
    )
    document = (
        tomllib.loads(path.read_text())
        if tool == "codex"
        else json.loads(path.read_text())
        if tool == "claude"
        else yaml.safe_load(path.read_text())
    )
    servers = document["mcpServers" if tool == "claude" else "mcp_servers"]
    assert servers["team_memory_github"] == stable
    assert servers["team_memory_hub"]["env"]["TEAM_MEMORY_ROOT"] == str(root)
    assert (
        "/.config/team-memory-hub/outbox"
        in servers["team_memory_hub"]["env"]["TEAM_MEMORY_OUTBOX"]
    )
    assert (folder / "SKILL.md").read_text() == "existing customized stable skill"
    assert (folder.parent / "team-memory-hub-archive/SKILL.md").is_file()


def test_hub_installer_has_independent_defaults():
    source = Path(__file__).resolve().parents[1]
    text = (source / "scripts/install.py").read_text()
    assert "https://github.com/newlightlw/agent-team-memory-hub.git" in text
    assert "~/.local/share/team-memory-hub/" in text
    assert '"team-memory-hub.cmd"' in text
    assert '"team-memory-github.cmd"' not in text
    assert (
        "local.team-memory-hub.sync"
        in (source / "team_memory/archive_setup.py").read_text()
    )


def test_existing_remote_marker_is_not_recreated_when_github_size_is_stale(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from team_share import admin

    root = tmp_path / "hub"
    admin.initialize(
        root, ["alice", "bob"], "https://memory.example.com", "example/private-hub"
    )
    writes = []

    def fake_run(args, **kwargs):
        if args == ["gh", "api", "repos/example/private-hub"]:
            return json.dumps(
                {"private": True, "permissions": {"admin": True}, "size": 0}
            )
        if args[0] == "ssh-keygen":
            key = Path(args[-1])
            key.write_text("synthetic private placeholder")
            key.with_suffix(".pub").write_text("ssh-ed25519 synthetic-public-test")
            return ""
        if args == ["gh", "api", "meta"]:
            return json.dumps({"ssh_keys": ["ssh-ed25519 synthetic-host-test"]})
        writes.append(args)
        return "{}"

    monkeypatch.setattr(admin, "run", fake_run)
    monkeypatch.setattr(
        admin.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0, stdout='{"type":"file"}', stderr=""
        ),
    )
    assert admin.connect_git(root)["readonly_key_registered"]
    assert len(writes) == 1 and writes[0][4].endswith("/keys")
