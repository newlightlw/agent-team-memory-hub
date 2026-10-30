"""Fresh all-in-one wheel runtime: account-free demo, private init, backup/restore."""

import json
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

source = Path(__file__).resolve().parents[1]
wheel = Path(sys.argv[1]).resolve()


def run(args, **kwargs):
    r = subprocess.run(
        list(map(str, args)),
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        **kwargs,
    )
    if r.returncode:
        raise RuntimeError(
            "fresh wheel check failed: "
            + Path(str(args[0])).name
            + " "
            + r.stderr[-1000:]
        )
    return r.stdout


with zipfile.ZipFile(wheel) as z:
    assert all(
        "team_share/viewer/static/" + name in z.namelist()
        for name in ("app.js", "style.css", "index.html")
    )
with tempfile.TemporaryDirectory(prefix="team-memory-fresh-") as tmp:
    root = Path(tmp)
    venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(
        root / "venv"
    )
    python = root / "venv/bin/python"
    run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "-r",
            source / "requirements/server.lock",
        ],
        cwd=root,
    )
    run([python, "-m", "pip", "install", "--no-deps", wheel], cwd=root)
    run([root / "venv/bin/team-memory-hub-admin", "--help"], cwd=root)
    demo = run([python, "-m", "team_share.collaboration", "demo", "--smoke"], cwd=root)
    assert "DEMO_ONLY" in demo and "PASS" in demo
    admin = [python, "-m", "team_share.admin"]
    run(
        [
            *admin,
            "init",
            root / "instance",
            "--url",
            "https://memory.example.com",
            "--repo",
            "example/private-memory",
            "--members",
            "alice",
            "bob",
        ],
        cwd=root,
    )
    check = json.loads(run([*admin, "doctor", root / "instance"], cwd=root))
    assert (
        check["real_two_person_acceptance"] == "NOT_RUN"
        and check["active_web_accounts"] == 2
    )
    run(
        [
            *admin,
            "backup",
            root / "instance",
            root / "backup.fernet",
            "--key-file",
            root / "key",
        ],
        cwd=root,
    )
    run(
        [
            *admin,
            "restore",
            root / "backup.fernet",
            root / "restored",
            "--key-file",
            root / "key",
        ],
        cwd=root,
    )
    assert (
        json.loads(run([*admin, "doctor", root / "restored"], cwd=root))[
            "active_web_accounts"
        ]
        == 2
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "fresh_wheel_install": True,
                "viewer_assets": True,
                "demo": True,
                "init_and_account_backup_restore": True,
                "external_accounts_used": False,
            }
        )
    )
