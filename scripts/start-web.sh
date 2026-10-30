#!/usr/bin/env bash
# 团队记忆 Web 共享服务 — 管理员在服务器上启动一次, 全员用 WEB_PUBLIC_URL 访问。
set -euo pipefail

MEMORY_ROOT="${TEAM_MEMORY_ROOT:-$HOME/team-memory}"
PYTHON="${TEAM_MEMORY_PYTHON:-python3}"
HOST="${WEB_HOST:-}"
PORT="${WEB_PORT:-}"

ARGS=(-m team_memory web -p "$MEMORY_ROOT" --no-browser)
if [[ -n "$HOST" ]]; then ARGS+=(--host "$HOST"); fi
if [[ -n "$PORT" ]]; then ARGS+=(--port "$PORT"); fi

exec "$PYTHON" "${ARGS[@]}"
