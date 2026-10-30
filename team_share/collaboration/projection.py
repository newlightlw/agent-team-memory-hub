"""Versioned Markdown projection in a NEW, gateway-owned Git repository only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..models import MemoryEntry, MemoryScope, MemoryStatus, MemoryType, serialize_memory

MARKER = ".collaboration-owned"


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("knowledge projection Git operation failed")
    return result.stdout


def export(store, *, purge=False):
    root = store.root / "knowledge"
    if root.is_symlink():
        raise ValueError("knowledge path must not be a symlink")
    if root.exists() and not (root / MARKER).is_file():
        raise ValueError("refusing to modify a repository not owned by this service")
    if purge and root.exists():
        # Dedicated local projection only. No force-push, no existing user repo.
        # SQLite revision history for surviving records is retained separately.
        shutil.rmtree(root)
    root.mkdir(exist_ok=True)
    (root / MARKER).touch()
    if not (root / ".git").exists():
        git(root, "init", "--initial-branch=main")
        git(root, "config", "user.name", "Team Collaboration")
        git(root, "config", "user.email", "collaboration@localhost")
    (root / ".team-memory.yml").write_text("team_name: Shared Team\ndefault_author: service\n")
    items = store.all(history=True)
    expected = set()
    for item in items:
        if item["kind"] in ("share", "response", "digest"):
            continue  # Raw messages and automatic extracts stay outside Git.
        if item["kind"] == "decision" and item["status"] in ("active", "superseded"):
            path = root / "memory" / "decisions" / f'{item["id"]}.md'
            status = MemoryStatus.ACTIVE if item["status"] == "active" else MemoryStatus.SUPERSEDED
            text = serialize_memory(MemoryEntry(
                id=item["id"], type=MemoryType.DECISION, title=item["title"],
                scope=MemoryScope.TEAM, author=item["author"], source=item["source"],
                created=item["created"][:10], updated=item["updated"][:10],
                status=status, superseded_by=item["replaced_by"], body=item["body"],
                evidence=tuple(store.parents(item["id"])),
            ))
        else:
            path = root / item["kind"] / f'{item["id"]}.md'
            text = f'# {item["title"]}\n\n' + item["body"] + "\n\n```json\n" + json.dumps({
                k: item[k] for k in ("id", "author", "created", "updated", "status", "revision", "data")
            }, ensure_ascii=False, indent=2) + "\n```\n\n来源: " + ", ".join(store.parents(item["id"])) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        expected.add(path)
    for path in root.rglob("*.md"):
        if ".git" not in path.parts and path not in expected:
            path.unlink()
    git(root, "add", "--all")
    if git(root, "status", "--porcelain"):
        git(root, "commit", "-m", "Update shared knowledge projection")
    return root
