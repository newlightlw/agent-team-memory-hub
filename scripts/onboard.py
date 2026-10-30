#!/usr/bin/env python3
"""Compatibility entry for member installation. Stops immediately on failure.
Usage: python3.11 scripts/onboard.py GITHUB_MEMORY_REPO author [--tools codex]
"""

from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                str(Path(__file__).with_name("install.py")),
                "--repo",
                sys.argv[1],
                "--author",
                sys.argv[2],
                *sys.argv[3:],
            ]
        )
    )
