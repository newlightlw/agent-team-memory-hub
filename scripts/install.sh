#!/usr/bin/env bash
# Member bootstrap for macOS/Linux. No sudo or global Python installation.
set -euo pipefail
TEAM_MEMORY_PYTHON=''
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,11))' >/dev/null 2>&1; then
    TEAM_MEMORY_PYTHON=$(command -v "$candidate")
    break
  fi
done
if [[ -z "$TEAM_MEMORY_PYTHON" ]] && command -v uv >/dev/null 2>&1; then
  TEAM_MEMORY_PYTHON=$(uv python find 3.11 2>/dev/null || true)
fi
if [[ -z "$TEAM_MEMORY_PYTHON" ]] || ! "$TEAM_MEMORY_PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3,11))' >/dev/null 2>&1; then
  echo 'Python 3.11+ is required. Install it first, or use an existing uv-managed Python.' >&2
  exit 1
fi
command -v git >/dev/null 2>&1 || { echo 'Git is required.' >&2; exit 1; }
# Use the adjacent installer only when explicitly running the repository script.
# A streamed/downloaded shell script never runs an unrelated cwd/install.py.
if [[ "${BASH_SOURCE[0]:-}" == */scripts/install.sh ]] && [[ -f "$(dirname "${BASH_SOURCE[0]}")/install.py" ]]; then
  "$TEAM_MEMORY_PYTHON" "$(dirname "${BASH_SOURCE[0]}")/install.py" "$@"
else
  # Avoid a second raw.githubusercontent.com request: use bounded Git HTTPS.
  "$TEAM_MEMORY_PYTHON" - "$@" <<'PY'
import pathlib, subprocess, sys, tempfile
with tempfile.TemporaryDirectory(prefix='team-memory-bootstrap-') as directory:
    source=pathlib.Path(directory)/'tool'
    result=subprocess.run(['git','clone','--depth','1','--branch','v0.5.0-candidate.1','--','https://github.com/newlightlw/agent-team-memory-hub.git',str(source)],capture_output=True,text=True,timeout=60)
    if result.returncode:
        raise SystemExit('Git bootstrap failed. Check GitHub access; no success claimed.')
    raise SystemExit(subprocess.call([sys.executable,str(source/'scripts/install.py'),*sys.argv[1:]]))
PY
fi
