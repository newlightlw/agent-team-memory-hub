#!/usr/bin/env python3
"""迁移旧 id (mem-DATE-NNN) 到新格式 (mem-DATE-{author}-NNN)。

背景: 旧 id 全局序号, 多人同天 capture 会撞号。新格式把 author 入 id,
每人独立序号空间。本脚本对已有仓库做一次性迁移:
  1. 每条旧格式 id 加入 author 段(取自 frontmatter author 的 ascii slug)
  2. 同步更新全仓库 related / superseded_by 引用
  3. 重命名文件
幂等: 已是新格式的 id 会被跳过。

用法: python3 scripts/migrate-ids.py [记忆仓库路径, 默认 ./demo-memory]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

OLD_ID_RE = re.compile(r"^mem-(\d{8})-(\d{3})$")
ID_LINE_RE = re.compile(r"^id:\s*(\S+)\s*$", re.M)
AUTHOR_LINE_RE = re.compile(r"^author:\s*(.+?)\s*$", re.M)


def author_slug(author: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", (author or "").lower())


def migrate(repo: Path) -> int:
    memory = repo / "memory"
    if not memory.exists():
        print(f"✗ 未找到 {memory}", file=sys.stderr)
        return 1

    # 1. 收集旧 id -> 新 id 映射 + 待改文件
    id_map: dict[str, str] = {}
    pending: list[tuple[Path, str, str]] = []
    skipped: list[tuple[Path, str]] = []

    for md in sorted(memory.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        id_m = ID_LINE_RE.search(text)
        if not id_m:
            continue
        old_id = id_m.group(1).strip().strip("'\"")
        if not OLD_ID_RE.match(old_id):
            continue  # 新格式或非法, 跳过
        auth_m = AUTHOR_LINE_RE.search(text)
        author = auth_m.group(1).strip().strip("'\"") if auth_m else ""
        slug = author_slug(author)
        if not slug:
            skipped.append((md, f"author {author!r} 无 ascii slug"))
            continue
        date, seq = OLD_ID_RE.match(old_id).group(1), OLD_ID_RE.match(old_id).group(2)
        new_id = f"mem-{date}-{slug}-{seq}"
        if new_id in id_map.values():
            skipped.append((md, f"新 id {new_id} 已存在(同 author 同 seq 冲突)"))
            continue
        id_map[old_id] = new_id
        pending.append((md, old_id, new_id))

    # 2. 改 id 行 + 重命名文件
    for md, old_id, new_id in pending:
        text = md.read_text(encoding="utf-8")
        text = text.replace(f"id: {old_id}", f"id: {new_id}", 1)
        md.write_text(text, encoding="utf-8")
        new_name = md.name.replace(old_id, new_id, 1)
        if new_name != md.name:
            md.rename(md.parent / new_name)

    # 3. 全仓库更新 related / superseded_by 引用(所有 .md)
    if id_map:
        for md in memory.rglob("*.md"):
            text = md.read_text(encoding="utf-8")
            new_text = text
            for old, new in id_map.items():
                new_text = new_text.replace(old, new)
            if new_text != text:
                md.write_text(new_text, encoding="utf-8")

    print(f"✓ 迁移完成: {len(pending)} 条 id 更新")
    for _, old, new in pending:
        print(f"  {old} → {new}")
    if skipped:
        print(f"\n⚠ 跳过 {len(skipped)} 个文件(需手动处理):")
        for md, reason in skipped:
            print(f"  {md.name}: {reason}")
    return 0


if __name__ == "__main__":
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./demo-memory")
    sys.exit(migrate(repo.resolve()))
