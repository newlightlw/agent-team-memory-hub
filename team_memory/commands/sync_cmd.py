"""Fail-closed Git synchronization. Never auto-commit, stash, reset, rebase or force-push."""

from __future__ import annotations
from pathlib import Path
from rich.console import Console
from ..config import load_config
from ..gitutil import run_git, get_remote_url, working_tree_dirty, is_rebase_in_progress
from ..store import MemoryStore


def sync_cmd(
    root: Path | None = None, *, push=True, pull=True, force=False, console=None
) -> bool:
    console = console or Console()
    store = MemoryStore.open(root)
    if push:
        store.assert_writable()
    reader_mode = (
        run_git(
            store.root, "config", "--local", "--get", "team-memory.readOnly"
        ).stdout.strip()
        == "true"
    )
    config = None if reader_mode else load_config(store.root / ".env")
    from ..sharing import same_remote, validate_remote

    expected = (
        ""
        if reader_mode or config.is_remote_placeholder
        else config.resolved_remote_url()
    )
    actual = get_remote_url(store.root)
    remote = actual or expected
    if not remote:
        console.print("[red]No origin or REMOTE_URL configured[/]")
        return False
    validate_remote(remote)
    if expected and actual and not same_remote(expected, actual):
        console.print(
            "[red]Configured remote differs from origin; no remote changed[/]"
        )
        return False
    if config is not None and config.is_remote_placeholder and not actual:
        console.print("[red]Remote URL is still a placeholder[/]")
        return False
    if is_rebase_in_progress(store.root):
        console.print("[red]Unfinished rebase; finish or abort it before sync[/]")
        return False
    if working_tree_dirty(store.root) and not force:
        console.print(
            "[red]Uncommitted changes; commit or preserve them before syncing[/]"
        )
        return False
    if not actual and run_git(store.root, "remote", "add", "origin", remote).returncode:
        console.print("[red]Could not add origin[/]")
        return False
    branch = run_git(store.root, "symbolic-ref", "--short", "HEAD")
    if branch.returncode:
        console.print("[red]Detached HEAD; select a branch before sync[/]")
        return False
    name = branch.stdout.strip()
    if pull:
        # An empty remote allows a first push, but a failed network request NEVER
        # authorizes a push. Explicit branch selection avoids missing-upstream bugs.
        heads = run_git(
            store.root, "ls-remote", "--heads", "origin", "refs/heads/" + name
        )
        if heads.returncode:
            console.print("[red]Remote unavailable; stopped before push[/]")
            return False
        if heads.stdout.strip():
            fetch = run_git(store.root, "fetch", "--no-tags", "origin", name)
            if (
                fetch.returncode
                or run_git(store.root, "merge", "--ff-only", "FETCH_HEAD").returncode
            ):
                console.print(
                    "[red]Fast-forward unavailable; no rebase, reset or push performed[/]"
                )
                return False
        elif not push:
            console.print("[red]Remote branch not found[/]")
            return False
    if push and run_git(store.root, "push", "-u", "origin", "HEAD").returncode:
        console.print("[red]Push failed; no forced update attempted[/]")
        return False
    console.print("[green]Git synchronization complete[/]")
    return True
