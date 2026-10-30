"""Install the built wheel into a fresh runtime and verify templates + CLI. No accounts."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import venv


def run(args, **kwargs):
    result = subprocess.run(
        [str(x) for x in args], capture_output=True, text=True, timeout=600, **kwargs
    )
    if result.returncode:
        raise RuntimeError(
            "Wheel verification command failed: "
            + Path(str(args[0])).name
            + "; "
            + result.stderr[-1500:]
        )
    return result.stdout


if __name__ == "__main__":
    wheel = Path(sys.argv[1]).resolve()
    source = Path(__file__).resolve().parent.parent
    version = tomllib.loads((source / "pyproject.toml").read_text())["project"][
        "version"
    ]
    with tempfile.TemporaryDirectory(prefix="team-memory-wheel-") as temp:
        root = Path(temp)
        venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(
            root / "venv"
        )
        python = root / (
            "venv/Scripts/python.exe" if sys.platform == "win32" else "venv/bin/python"
        )
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                source / "requirements/runtime.lock",
            ],
            cwd=root,
        )
        run([python, "-m", "pip", "install", "--no-deps", wheel], cwd=root)
        check = (
            "from team_memory.templating import TEMPLATES_DIR; import team_memory; "
            + f"assert team_memory.__version__=={version!r}; "
            + 'assert (TEMPLATES_DIR/"repo/.gitignore").is_file(); '
            + 'assert (TEMPLATES_DIR/"skills/auto-commit-memory/SKILL.md").is_file(); '
            + 'assert (TEMPLATES_DIR/"types/project.md").is_file()'
        )
        run([python, "-c", check], cwd=root)
        # Base/member installation must stay usable without server dependencies.
        unavailable = subprocess.run([root / "venv/bin/team-memory-hub-admin", "--help"], cwd=root, capture_output=True, text=True, timeout=30)
        assert unavailable.returncode != 0 and "Server dependencies are not installed" in unavailable.stderr

        run(
            [
                python,
                "-m",
                "team_memory",
                "init",
                "-p",
                root / "data",
                "-n",
                "Synthetic",
                "-a",
                "demo",
            ],
            cwd=root,
        )
        assert (root / "data/memory/project/_template.md").is_file()
        assert (root / "data/.gitignore").is_file()
        run(
            [
                python,
                "-m",
                "team_memory",
                "propose",
                "Synthetic draft",
                "-t",
                "project",
                "--author",
                "demo",
                "--note",
                "DEMO_ONLY",
                "-p",
                root / "data",
            ],
            cwd=root,
        )
        assert list((root / "data/inbox").glob("mem-*.md"))
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "fresh_wheel_install": True,
                    "templates_present": True,
                    "cli_init_and_propose": True,
                    "accounts_used": False,
                }
            )
        )
