"""Review selected public sources and actual installed dependency license metadata."""

import importlib.metadata
import json
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
tracked = subprocess.run(
    ["git", "ls-files", "-co", "--exclude-standard", "-z"],
    cwd=root,
    capture_output=True,
    text=True,
    check=True,
).stdout.split("\0")
violations = []
for name in tracked:
    if not name:
        continue
    p = root / name
    if not p.is_file():
        continue
    if p.suffix in (".sqlite3", ".fernet", ".pem") or p.name in (
        "secrets.env",
        "auth.json",
        "viewer-accounts.json",
    ):
        violations.append(name + ": forbidden instance artifact")
        continue
    if name.startswith(("scripts/audit-distribution.py", "tests/")):
        continue
    text = p.read_text(errors="replace")
    if re.search(
        r"175\.178\.59\.206|(?:team-memory|heretoo)\.manisfast\.com|/Users/vayne|/home/liw",
        text,
    ):
        violations.append(name + ": personal deployment reference")
    if re.search(
        r"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{20,}",
        text,
    ):
        violations.append(name + ": potential credential literal")
licenses = []
for d in importlib.metadata.distributions():
    # License text can span hundreds of lines; retain declared SPDX or license classifiers only.
    licenses.append(
        {
            "name": d.metadata["Name"],
            "version": d.version,
            "license": d.metadata.get("License-Expression")
            or ", ".join(
                x
                for x in (d.metadata.get_all("Classifier") or [])
                if x.startswith("License ::")
            )
            or (d.metadata.get("License") or "not declared").splitlines()[0][:160],
        }
    )
print(
    json.dumps(
        {
            "source_scan": "PASS" if not violations else "FAIL",
            "violations": violations,
            "dependencies": sorted(licenses, key=lambda x: x["name"].lower()),
            "scope": "literal scan and metadata inventory; not a security or legal certification",
        },
        ensure_ascii=False,
        indent=2,
    )
)
raise SystemExit(bool(violations))
