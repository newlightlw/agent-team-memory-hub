#!/usr/bin/env bash
set -euo pipefail
# Paths are configurable; GitHub key must be a read-only deploy key for DATA repo.
base=${TEAM_VIEWER_DATA:-$HOME/.local/share/team-memory-viewer}
keys=${TEAM_VIEWER_KEYS:-$HOME/.config/team-memory-viewer}
repo=${TEAM_VIEWER_REPO:?Set your own DATA repository SSH URL}
mkdir -p "$base"
chmod 700 "$base"
exec 9>"$base/git-sync.lock"
flock -n 9 || exit 0
export GIT_SSH_COMMAND="ssh -i $keys/github-readonly -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$keys/github-known-hosts -o BatchMode=yes -o ConnectTimeout=10"
if [[ ! -d "$base/git-cache/.git" ]]; then
 [[ ! -e "$base/git-cache" ]] || { echo 'Existing non-Git destination preserved'; exit 1; }
 git clone --quiet --single-branch --branch main -- "$repo" "$base/git-cache"
 git -C "$base/git-cache" config --local remote.origin.pushurl disabled://readonly
fi
[[ "$(git -C "$base/git-cache" remote get-url origin)" == "$repo" ]] || exit 1
git -C "$base/git-cache" diff --quiet
git -C "$base/git-cache" diff --cached --quiet
git -C "$base/git-cache" pull --quiet --ff-only origin main
date -u +%Y-%m-%dT%H:%M:%SZ > "$base/last-sync"
