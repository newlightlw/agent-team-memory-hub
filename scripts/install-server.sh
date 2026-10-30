#!/usr/bin/env bash
# Isolated, pinned server installer. No sudo, no service activation, no model login.
set -euo pipefail
if [[ $# != 1 || "$1" != /* ]]; then echo 'Usage: bash scripts/install-server.sh /absolute/new/install-root' >&2; exit 1; fi
install_root=$1
[[ ! -e "$install_root" && ! -L "$install_root" ]] || { echo 'Existing installation preserved; choose a new release directory' >&2; exit 1; }
python_bin=''
for candidate in python3.13 python3.12 python3.11 python3; do
 if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys;raise SystemExit(sys.version_info < (3,11))' >/dev/null 2>&1; then python_bin=$(command -v "$candidate"); break; fi
done
[[ -n "$python_bin" ]] || { echo 'Python 3.11+ required'; exit 1; }
command -v git >/dev/null
source_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ -f "$source_root/requirements/server.lock" && -f "$source_root/pyproject.toml" ]] || { echo 'Run from the checked-out v0.5.0-candidate.1 source'; exit 1; }
mkdir -p "$install_root"
chmod 700 "$install_root"
"$python_bin" -m venv "$install_root/venv"
"$install_root/venv/bin/python" -m pip install --require-hashes -r "$source_root/requirements/server.lock"
"$install_root/venv/bin/python" -m pip install --no-deps --no-build-isolation "$source_root"
"$install_root/venv/bin/team-memory-hub-admin" --help >/dev/null
echo 'PASS: isolated server software installed; no instance initialized or services activated.'
echo "Next: $install_root/venv/bin/team-memory-hub-admin wizard /absolute/new/private-instance"
