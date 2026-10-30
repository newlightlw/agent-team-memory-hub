#!/usr/bin/env python3
"""One-command member installer: isolated Python, private Git cache, selected MCP clients.
Requires Python 3.11+, Git, and existing GitHub access to the private data repo.
Never runs sudo, installs into system Python, reads publisher tokens or pushes memories.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv

TOOL_REPO = "https://github.com/newlightlw/agent-team-memory-hub.git"
RELEASE = "v0.5.0-candidate.1"


def run(args, **kwargs):
    result = subprocess.run(
        [str(x) for x in args],
        capture_output=True,
        text=True,
        timeout=kwargs.pop("timeout", 300),
        **kwargs,
    )
    if result.returncode:
        raise RuntimeError(
            "Command failed: "
            + Path(str(args[0])).name
            + " "
            + str(args[1] if len(args) > 1 else "")
            + "; check GitHub access, Python dependencies, and paths. No success claimed."
        )
    return result.stdout


def install(args):
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11+ required")
    url = args.repo
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url):
        url = "https://github.com/" + url + ".git"
    if not re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?",
        url,
    ):
        raise ValueError("Use a credential-free GitHub OWNER/REPO, HTTPS or SSH URL")
    if (
        url.rstrip("/").removesuffix(".git").endswith("/newlightlw/agent-team-memory-hub")
        or url == "git@github.com:newlightlw/agent-team-memory-hub.git"
    ):
        raise ValueError("Supply the DATA repository, not the public tool repository")
    if not re.fullmatch(r"[a-z0-9_]{1,32}", args.author):
        raise ValueError("Author must be lowercase ASCII, e.g. kiki")
    tools = args.tools.split(",")
    if any(t not in ("codex", "claude", "hermes", "none") for t in tools):
        raise ValueError("Select --tools codex,claude,hermes or none")
    repo_id = url.removeprefix("https://github.com/").removeprefix("git@github.com:").removesuffix(".git")
    if args.enable_upload:
        gh = shutil.which("gh")
        if not gh:
            raise ValueError("Install GitHub CLI gh and authenticate your own account before enabling uploads")
        access = json.loads(run([gh, "api", "--hostname", "github.com", "repos/" + repo_id]))
        if access.get("private") is not True or access.get("permissions", {}).get("push") is not True:
            raise ValueError("Enabled archives require your own WRITE access to a PRIVATE data repository")
    home = Path.home()
    base = args.install_root.expanduser().absolute()
    data = args.path.expanduser().absolute()
    if base.is_symlink() or data.is_symlink():
        raise ValueError("Installation/cache symlinks require manual setup")
    if base == data or base.is_relative_to(data):
        raise ValueError("Tool installation cannot be inside the Git data cache")
    wrapper = (
        home
        / ".local/bin"
        / ("team-memory-hub.cmd" if os.name == "nt" else "team-memory-hub")
    )
    if (
        wrapper.is_symlink()
        or wrapper.exists()
        and "team-memory-hub-managed" not in wrapper.read_text()
    ):
        raise ValueError(
            "Existing team-memory-hub command is not managed; no command replaced"
        )
    # Preflight access before installing dependencies or modifying client configs.
    run(["git", "ls-remote", "--exit-code", url, "HEAD"], timeout=45)
    metadata = base / "installed.json"
    python = base / (
        "venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python"
    )
    if base.exists():
        if metadata.is_symlink() or not metadata.is_file():
            raise ValueError(
                "Existing installation directory is not managed; choose another --install-root"
            )
        old = json.loads(metadata.read_text())
        if old.get("release") != RELEASE or old.get("source") != TOOL_REPO:
            raise ValueError("Existing installation differs; no overwrite")
        if (
            run(
                [python, "-c", "import team_memory; print(team_memory.__version__)"]
            ).strip()
            != "0.5.0rc1"
        ):
            raise ValueError("Installed environment damaged; select a new install root")
    else:
        base.mkdir(parents=True, mode=0o700)
        source = base / "source"
        tool_source = getattr(args, "tool_source", None)
        if tool_source:
            # Developer verification only. Not used by the published one-command path.
            run(["git", "clone", "--no-hardlinks", "--", tool_source, source])
        else:
            run(
                [
                    "git",
                    "clone",
                    "--branch",
                    RELEASE,
                    "--depth",
                    "1",
                    "--",
                    TOOL_REPO,
                    source,
                ],
                timeout=60,
            )
        commit = run(["git", "-C", source, "rev-parse", "HEAD"]).strip()
        print(
            "Installing pinned tool "
            + RELEASE
            + " ("
            + commit[:12]
            + ") in a private virtual environment...",
            flush=True,
        )
        venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(
            base / "venv"
        )
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--require-hashes",
                "-r",
                source / "requirements/runtime.lock",
            ],
            timeout=600,
        )
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-build-isolation",
                source,
            ],
            timeout=180,
        )
        # A wheel install must contain its templates, not rely on the source checkout.
        run(
            [
                python,
                "-c",
                'from team_memory.templating import TEMPLATES_DIR; assert (TEMPLATES_DIR/"repo/.gitignore").is_file(); assert (TEMPLATES_DIR/"types/project.md").is_file()',
            ]
        )
        metadata.write_text(
            json.dumps(
                {
                    "release": RELEASE,
                    "source": TOOL_REPO,
                    "commit": commit,
                    "development_override": bool(tool_source),
                },
                indent=2,
            )
            + "\n"
        )
        metadata.chmod(0o600)
    run([python, "-m", "team_memory", "join", url, "-p", data], timeout=90)
    script = 'from pathlib import Path;import json,sys;from team_memory.member_setup import configure_clients;print(json.dumps(configure_clients(Path(sys.argv[1]),Path(sys.executable),sys.argv[2].split(","),author=sys.argv[3],upload_repo=sys.argv[4] or None)))'
    configured = json.loads(run([python, "-c", script, data, args.tools, args.author, repo_id if args.enable_upload else ""]))
    bindir = home / ".local/bin"
    bindir.mkdir(parents=True, exist_ok=True)
    wrapper = bindir / (
        "team-memory-hub.cmd" if os.name == "nt" else "team-memory-hub"
    )
    if (
        wrapper.is_symlink()
        or wrapper.exists()
        and "team-memory-hub-managed" not in wrapper.read_text()
    ):
        raise ValueError(
            "Existing team-memory-hub command is not managed; no command replaced"
        )
    if os.name == "nt":
        content = (
            '@rem team-memory-hub-managed\r\n@cd /d "'
            + str(data)
            + '"\r\n@"'
            + str(python)
            + '" -m team_memory %*\r\n'
        )
    else:
        content = (
            "#!/bin/sh\n# team-memory-hub-managed\ncd "
            + shlex.quote(str(data))
            + " || exit 1\nexec "
            + shlex.quote(str(python))
            + ' -m team_memory "$@"\n'
        )
    fd, temp = tempfile.mkstemp(dir=bindir, prefix=".team-memory-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.chmod(temp, 0o700)
        os.replace(temp, wrapper)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print(
        json.dumps(
            {
                "status": "PASS",
                "release": RELEASE,
                "cache": str(data),
                "command": str(wrapper),
                "mcp_name": configured["mcp_name"],
                "client_configs": configured["configured"],
                "backup_directory": configured["backup_directory"],
                "memory_uploaded": False,
                "restart_clients": "Reload MCP or open a new client session. Authentication/approvals remain client-controlled.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--tools", default="codex")
    parser.add_argument("--enable-upload", action="store_true", help="Enable explicit archive requests to this private GitHub data repo")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("~/.local/share/team-memory-hub/team-shared-memory"),
    )
    parser.add_argument(
        "--install-root",
        type=Path,
        default=Path("~/.local/share/team-memory-hub/releases/" + RELEASE),
    )
    parser.add_argument("--tool-source", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        install(args)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print("Installation not completed: " + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
