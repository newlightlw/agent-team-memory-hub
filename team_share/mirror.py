"""Read-only GitHub deploy-key mirror, Linux/macOS; fast-forward only."""

import argparse
import fcntl
import os
import shlex
from datetime import UTC
from pathlib import Path

from .admin import atomic_private, read_instance


def sync(root):
    root, info, _ = read_instance(root)
    base = root / "mirror"
    base.mkdir(mode=0o700, exist_ok=True)
    keys = root / "keys"
    if not all(
        (keys / name).is_file() for name in ("github-readonly", "github-known-hosts")
    ):
        raise ValueError(
            "registered readonly key and trusted GitHub host keys required"
        )
    remote = "git@github.com:" + info["repo"] + ".git"

    def git(*args):
        import subprocess

        env = {
            **os.environ,
            "GIT_SSH_COMMAND": f"ssh -i {shlex.quote(str(keys / 'github-readonly'))} -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile={shlex.quote(str(keys / 'github-known-hosts'))} -o BatchMode=yes -o ConnectTimeout=10",
            "GIT_TERMINAL_PROMPT": "0",
        }
        r = subprocess.run(
            ["git", *map(str, args)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        if r.returncode:
            raise RuntimeError("Readonly mirror failed; old snapshot retained")
        return r.stdout.strip()

    with open(base / "sync.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cache = base / "git-cache"
        if cache.is_symlink():
            raise ValueError("mirror symlink refused")
        if not cache.exists():
            # Atomic clone: a failed clone never leaves an apparently valid cache.
            import shutil
            import tempfile

            stage = Path(tempfile.mkdtemp(dir=base))
            try:
                git(
                    "clone",
                    "--quiet",
                    "--single-branch",
                    "--branch",
                    "main",
                    "--",
                    remote,
                    stage / "repo",
                )
                (stage / "repo").rename(cache)
            finally:
                shutil.rmtree(stage)
        if git("-C", cache, "remote", "get-url", "origin") != remote:
            raise ValueError("mirror remote differs")
        git(
            "-C",
            cache,
            "config",
            "--local",
            "remote.origin.pushurl",
            "disabled://readonly",
        )
        git("-C", cache, "diff", "--quiet")
        git("-C", cache, "diff", "--cached", "--quiet")
        if git("-C", cache, "status", "--porcelain"):
            raise ValueError("mirror dirty")
        git("-C", cache, "pull", "--quiet", "--ff-only", "origin", "main")
        from datetime import datetime

        atomic_private(base / "last-sync", datetime.now(UTC).isoformat())
    return {"synced": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--instance", type=Path, required=True)
    a = p.parse_args()
    try:
        sync(a.instance)
    except (ValueError, RuntimeError, OSError):
        raise SystemExit("Mirror failed; private values withheld") from None
