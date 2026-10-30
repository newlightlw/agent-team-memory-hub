"""Account-free shell bootstrap checks; no network, global profile or live installs."""

from pathlib import Path
import os
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1] / "scripts/install.sh"


def environment(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    # Supply a known supported interpreter without relying on the CI runner PATH.
    (binary / "python3.13").symlink_to(sys.executable)
    return {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]}, binary


def test_explicit_repository_script_uses_adjacent_installer(tmp_path):
    scripts = tmp_path / "tool/scripts"
    scripts.mkdir(parents=True)
    shell = scripts / "install.sh"
    shell.write_text(SOURCE.read_text())
    (scripts / "install.py").write_text(
        'import json,sys;print("ADJACENT "+json.dumps(sys.argv[1:]))'
    )
    env, _ = environment(tmp_path)
    result = subprocess.run(
        ["bash", str(shell), "--repo", "example/private", "--author", "demo"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'ADJACENT ["--repo", "example/private", "--author", "demo"]' in result.stdout


def test_streamed_script_ignores_cwd_installer_and_uses_pinned_git(tmp_path):
    env, binary = environment(tmp_path)
    (tmp_path / "install.py").write_text(
        'raise SystemExit("UNRELATED_CWD_MUST_NOT_RUN")'
    )
    fakegit = binary / "git"
    fakegit.write_text(
        """#!"""
        + sys.executable
        + """
from pathlib import Path
import sys
assert sys.argv[1:]==['clone','--depth','1','--branch','v0.5.0-candidate.1','--','https://github.com/newlightlw/agent-team-memory-hub.git',sys.argv[-1]]
p=Path(sys.argv[-1])/'scripts';p.mkdir(parents=True)
(p/'install.py').write_text('import sys;print("PINNED_GIT_SOURCE "+" ".join(sys.argv[1:]))')
"""
    )
    fakegit.chmod(0o700)
    result = subprocess.run(
        ["bash", "-s", "--", "--repo", "example/private", "--author", "demo"],
        input=SOURCE.read_text(),
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "PINNED_GIT_SOURCE --repo example/private --author demo" in result.stdout
    assert "UNRELATED_CWD_MUST_NOT_RUN" not in result.stdout + result.stderr
