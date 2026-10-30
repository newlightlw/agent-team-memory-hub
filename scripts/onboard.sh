#!/usr/bin/env bash
# 新人接入团队记忆仓库 — 一键脚本
# 用法: ./scripts/onboard.sh <记忆仓库git地址> <你的英文短名>
# 示例: ./scripts/onboard.sh https://git.example.com/team/team-memory.git zhang3
set -e

REPO_URL="$1"
AUTHOR="${2:-}"

if [ -z "$REPO_URL" ]; then
  echo "用法: $0 <记忆仓库git地址> <你的英文短名(用于id, 如 zhang3)>"
  echo "示例: $0 https://git.example.com/team/team-memory.git zhang3"
  exit 1
fi

# 工具仓库根(本脚本所在 scripts/ 的上一级)
TOOL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MEM_DIR="${MEM_DIR:-$HOME/team-memory}"

echo "=== 1. clone 记忆仓库到 $MEM_DIR ==="
if [ -d "$MEM_DIR/.git" ]; then
  echo "  已存在, 执行 git pull"
  git -C "$MEM_DIR" pull --rebase || true
else
  git clone "$REPO_URL" "$MEM_DIR"
fi

echo "=== 2. 安装 team-memory 工具 ==="
pip install -e "$TOOL_DIR" -q 2>/dev/null || pip install -e "$TOOL_DIR" -q

echo "=== 3. 配置 .env(GITEA_REMOTE_URL + DEFAULT_AUTHOR) ==="
ENV="$MEM_DIR/.env"
if [ ! -f "$ENV" ]; then
  cp "$MEM_DIR/.env.example" "$ENV" 2>/dev/null || echo "GITEA_REMOTE_URL=$REPO_URL" > "$ENV"
fi
# 平台兼容的 sed 原地替换(macOS 需备份后缀再删, Linux 直接 -i)
_sed() { sed -i.bak "$1" "$2" && rm -f "${2}.bak"; }
_sed "s|^GITEA_REMOTE_URL=.*|GITEA_REMOTE_URL=$REPO_URL|" "$ENV"
if [ -n "$AUTHOR" ]; then
  _sed "s|^DEFAULT_AUTHOR=.*|DEFAULT_AUTHOR=$AUTHOR|" "$ENV"
  echo "  DEFAULT_AUTHOR=$AUTHOR (用于记忆 id 的 author 段)"
fi
echo "  请按需补充 GITEA_TOKEN(或配 git credential)"

echo "=== 4. 桥接到 4 个 AI 工具(全局 skill) ==="
team-memory load --global -p "$MEM_DIR"

echo "=== 5. 自检 ==="
team-memory doctor -p "$MEM_DIR" || echo "  (有问题见上方, 可修后重跑)"

cat <<EOF

✓ 接入完成! 记忆仓库: $MEM_DIR

常用命令:
  沉淀:  team-memory capture "标题" -t decision --via claude -p $MEM_DIR
  查看:  team-memory list -p $MEM_DIR
  可视化: team-memory web -p $MEM_DIR   (浏览器自动打开)
  同步:  team-memory sync -p $MEM_DIR   (pull + push Git 远端)
  对话中: 直接说"提交下" → auto-commit-memory 自动总结并确认提交

【可选】让 AI 工具动态读写记忆(MCP):
  pip install -e "${TOOL_DIR}[mcp]"
  配置见 docs/MCP接入.md (Claude Code/Cursor/Codex/Hermes)
EOF
