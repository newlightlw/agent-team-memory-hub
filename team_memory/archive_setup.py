"""Configure exactly one designated member-computer summarizer, never cloud model auth."""

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from .archive_sync import private_json
from .member_setup import _atomic


def configure(path, repo, reader, tool, binary, team_id):
    import re

    path = Path(path).expanduser().absolute()
    reader = Path(reader).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("new private config path required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("OWNER/REPO required")
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", team_id):
        raise ValueError("valid team ID required")
    private_json(reader)
    binary = str(Path(binary).expanduser().absolute())
    if tool == "claude":
        from .claude_summarizer import probe

        probe(binary)
    else:
        from .archive_summarizer import probe

        probe(binary)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = path.with_suffix(".state.json")
    config = {
        "enabled": True,
        "repo": repo,
        "team_id": team_id,
        "reader_config": str(reader),
        "state": str(state),
        "gh": shutil.which("gh") or "gh",
        "interval_seconds": 60,
        "summary_command": [
            sys.executable,
            "-m",
            "team_memory.claude_summarizer"
            if tool == "claude"
            else "team_memory.archive_summarizer",
            "--" + tool,
            binary,
        ],
    }
    _atomic(path, json.dumps(config, indent=2))
    return {
        "configured": True,
        "private_config": str(path),
        "active": False,
        "designated_computer_only": True,
        "real_model_acceptance": "NOT_RUN",
    }


def main():
    p = argparse.ArgumentParser(prog="team-memory-hub-sync")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("configure")
    q.add_argument("--config", required=True, type=Path)
    q.add_argument("--repo", required=True)
    q.add_argument("--reader", required=True, type=Path)
    q.add_argument("--team-id", required=True)
    q.add_argument("--tool", choices=["codex", "claude"], required=True)
    q.add_argument("--binary", required=True)
    q = sub.add_parser("check")
    q.add_argument("--config", required=True, type=Path)
    q = sub.add_parser("render-startup")
    q.add_argument("--config", required=True, type=Path)
    q.add_argument("output", type=Path)
    a = p.parse_args()
    try:
        if a.command == "configure":
            result = configure(a.config, a.repo, a.reader, a.tool, a.binary, a.team_id)
        elif a.command == "check":
            cfg = private_json(a.config)
            private_json(cfg["reader_config"])

            status = Path(cfg["state"]).with_suffix(".status.json")
            result = {
                "config_valid": True,
                "enabled": cfg.get("enabled") is True,
                "model_probe_only": True,
                "real_model_acceptance": "NOT_RUN",
                "last_run": private_json(status) if status.exists() else None,
            }
            tool = cfg["summary_command"][-2]
            binary = cfg["summary_command"][-1]
            if tool == "--claude":
                from .claude_summarizer import probe
            else:
                from .archive_summarizer import probe
            result.update(probe(binary))
            permission = subprocess.run(
                [cfg.get("gh", "gh"), "api", "repos/" + cfg["repo"]],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if permission.returncode:
                result["github_private_write_permission"] = "FAIL"
            else:
                meta = json.loads(permission.stdout)
                result["github_private_write_permission"] = (
                    "PASS"
                    if meta.get("private") and meta.get("permissions", {}).get("push")
                    else "FAIL"
                )
            result["actual_write_acceptance"] = (
                "requires an explicit synthetic archive; not performed by check"
            )
        else:
            cfg = private_json(a.config)
            if a.output.exists():
                raise ValueError("fresh startup output required")
            a.output.mkdir(parents=True, mode=0o700)
            args = [
                sys.executable,
                "-m",
                "team_memory.archive_sync",
                "--config",
                str(a.config.expanduser().absolute()),
            ]
            # Environment may carry private proxy values: artifacts stay mode 600.
            env = {
                k: v
                for k, v in os.environ.items()
                if k
                in (
                    "PATH",
                    "HTTPS_PROXY",
                    "HTTP_PROXY",
                    "ALL_PROXY",
                    "NO_PROXY",
                    "SSL_CERT_FILE",
                    "SSL_CERT_DIR",
                )
            }
            log = a.config.with_suffix(".worker.log").absolute()
            plist = {
                "Label": "local.team-memory-hub.sync",
                "ProgramArguments": args,
                "RunAtLoad": True,
                "KeepAlive": True,
                "EnvironmentVariables": env,
                "StandardOutPath": str(log),
                "StandardErrorPath": str(log),
                "Umask": 63,
            }
            target = a.output / "local.team-memory-hub.sync.plist"
            target.write_bytes(plistlib.dumps(plist))
            target.chmod(0o600)

            unit = (
                "[Unit]\nDescription=Designated Team Memory summary computer\n[Service]\nUMask=0077\nExecStart="
                + " ".join(
                    '"' + x.replace("%", "%%").replace('"', '\\"') + '"' for x in args
                )
                + "\nRestart=on-failure\n[Install]\nWantedBy=default.target\n"
            )
            # systemd uses a private EnvironmentFile instead of placing proxy credentials in a public unit.
            environment = a.output / "sync.env"
            _atomic(
                environment,
                "\n".join(k + "=" + json.dumps(v) for k, v in env.items()) + "\n",
            )
            unit = unit.replace(
                "UMask=0077",
                "UMask=0077\nEnvironmentFile="
                + str(environment.absolute()).replace("%", "%%"),
            )
            _atomic(a.output / "team-memory-hub-sync.service", unit)
            result = {
                "rendered": True,
                "activated": False,
                "logs_contain": "counts/error classes only; no source bodies",
                "single_computer": "stop any previous designated worker before starting",
            }
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError):
        raise SystemExit("Sync setup failed; private values withheld") from None


if __name__ == "__main__":
    main()
