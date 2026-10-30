#!/usr/bin/env bash
# Web 服务器定时同步 — 从 Git 远端拉取 team-memory 最新记忆，供 Web UI 展示。
# 用法:
#   bash scripts/sync-web-server.sh
#   crontab: */5 * * * * /path/to/agent-team-memory/scripts/sync-web-server.sh
set -euo pipefail

MEM_ROOT="${TEAM_MEMORY_ROOT:-$HOME/team-memory}"
LOG="${TEAM_MEMORY_SYNC_LOG:-/tmp/team-memory-web-sync.log}"

if [[ ! -d "$MEM_ROOT/.git" ]]; then
  echo "$(date -Is) ERROR: 不是 git 仓库: $MEM_ROOT" >> "$LOG"
  exit 1
fi

cd "$MEM_ROOT"
before="$(git rev-parse HEAD)"
if git pull --rebase origin master >> "$LOG" 2>&1; then
  after="$(git rev-parse HEAD)"
  if [[ "$before" != "$after" ]]; then
    echo "$(date -Is) OK: updated $before -> $after" >> "$LOG"
  fi
else
  echo "$(date -Is) ERROR: git pull failed (see log above)" >> "$LOG"
  exit 1
fi
