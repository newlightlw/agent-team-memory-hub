"""记忆数据模型 — MemoryEntry + frontmatter 解析/序列化。

每条记忆统一为 YAML frontmatter + Markdown 正文:

    ---
    id: mem-20260623-001
    type: decision
    scope: team
    author: alice
    created: 2026-06-23
    status: active
    tags: [architecture]
    ---

    # 标题

    ## Context
    ...

设计要点:
  - MemoryEntry 是 frozen dataclass, 不可变(符合 immutability 约束)
  - tags/related 用 tuple 而非 list(不可变); 序列化时转 list
  - 废弃不删除: status=superseded 时用 superseded_by 指向新记忆
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

import yaml

__all__ = [
    "MemoryType",
    "MemoryScope",
    "MemoryStatus",
    "MemoryEntry",
    "MemoryParseError",
    "MemoryValidationError",
    "MEMORY_ID_PATTERN",
    "TYPE_DIR",
    "author_slug",
    "format_memory_id",
    "memory_id_author",
    "memory_id_date",
    "today_compact",
    "today_iso",
    "parse_memory",
    "serialize_memory",
    "validate_entry",
]


# 记忆 id 形如 mem-20260623-alice-001 (含 author, 每人独立序号空间防多人撞号)
MEMORY_ID_PATTERN = re.compile(r"^mem-(\d{8})-([a-z0-9_]+)-(\d{3})$")

# 五类记忆 -> 落盘目录名
TYPE_DIR: dict[str, str] = {
    "project": "project",
    "code": "code",
    "decision": "decisions",
    "error": "errors",
    "skill": "skills",
}


class MemoryType(StrEnum):
    PROJECT = "project"
    CODE = "code"
    DECISION = "decision"
    ERROR = "error"
    SKILL = "skill"


class MemoryScope(StrEnum):
    TEAM = "team"
    PROJECT = "project"
    MODULE = "module"
    PERSONAL = "personal"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"   # 候选记忆, 待人工 approve
    DEPRECATED = "deprecated"
    SUPERSEDED = "superseded"
    DECLINED = "declined"               # candidate 被拒绝
    CONFLICT = "conflict"               # 与其他记忆冲突
    PRIVATE = "private"                 # 个人私有, 不入团队共享


class MemoryParseError(ValueError):
    """记忆文件解析失败。"""


class MemoryValidationError(ValueError):
    """记忆条目校验未通过。"""


# frontmatter 字段输出顺序(保持可读、稳定 diff)
_FIELD_ORDER = (
    "id",
    "type",
    "scope",
    "author",
    "source",
    "role",
    "created",
    "updated",
    "expires",
    "status",
    "superseded_by",
    "confidence",
    "tags",
    "related",
    "evidence",
)
_REQUIRED_FIELDS = ("id", "type", "scope", "author", "created", "status")

# 匹配 frontmatter 块: ---\n<yaml>\n---\n<body>
_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
# 从 body 提取首个 '# 标题'(MULTILINE: 行尾可有可无换行)
_TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class MemoryEntry:
    """一条团队记忆。不可变; 修改请用 dataclasses.replace 产生新实例。"""

    id: str
    type: MemoryType
    title: str
    scope: MemoryScope = MemoryScope.TEAM
    author: str = ""
    source: str = ""
    role: str = ""
    created: str = ""
    updated: str = ""
    expires: str | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    superseded_by: str | None = None
    tags: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    confidence: str = ""
    body: str = ""

    def to_frontmatter_dict(self) -> dict[str, Any]:
        """序列化为可写入 YAML frontmatter 的 dict(不含 body)。"""
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type.value,
            "scope": self.scope.value,
            "author": self.author,
            "role": self.role,
            "created": self.created,
            "updated": self.updated or self.created,
            "status": self.status.value,
            "tags": list(self.tags),
            "related": list(self.related),
        }
        if self.expires:
            data["expires"] = self.expires
        if self.superseded_by:
            data["superseded_by"] = self.superseded_by
        if self.source:
            data["source"] = self.source
        if self.evidence:
            data["evidence"] = list(self.evidence)
        if self.confidence:
            data["confidence"] = self.confidence
        # 按稳定顺序输出
        return {key: data[key] for key in _FIELD_ORDER if key in data}


# ---------------------------------------------------------------------------
# 日期 / id 工具
# ---------------------------------------------------------------------------


def today_compact() -> str:
    """返回 20260623, 用于记忆 id。"""
    return date.today().strftime("%Y%m%d")


def today_iso() -> str:
    """返回 2026-06-23, 用于 created/updated 字段。"""
    return date.today().isoformat()


def author_slug(author: str) -> str:
    """把 author 转 id 安全的 ascii slug(小写, 仅 a-z0-9_); 非ascii/空返回空串。"""
    return re.sub(r"[^a-z0-9_]", "", (author or "").lower())


def format_memory_id(date_compact: str, author: str, seq: int) -> str:
    """生成形如 mem-20260623-alice-001 的记忆 id(author 入 id, 每人独立序号空间)。"""
    slug = author_slug(author)
    if not slug:
        raise ValueError(
            f"author 必须含 ascii 字母数字(用于 id 段): {author!r}; "
            "请在 .env 配 DEFAULT_AUTHOR=<英文短名>, 或 --author 传入"
        )
    return f"mem-{date_compact}-{slug}-{seq:03d}"


def memory_id_date(memory_id: str) -> str | None:
    """从记忆 id 提取 8 位日期, 非法返回 None。"""
    match = MEMORY_ID_PATTERN.match(memory_id)
    return match.group(1) if match else None


def memory_id_author(memory_id: str) -> str | None:
    """从记忆 id 提取 author 段, 非法返回 None。"""
    match = MEMORY_ID_PATTERN.match(memory_id)
    return match.group(2) if match else None


# ---------------------------------------------------------------------------
# 解析 / 序列化
# ---------------------------------------------------------------------------


def _extract_title(body: str) -> str:
    match = _TITLE_RE.search(body)
    return match.group(1).strip() if match else ""


def parse_memory(text: str) -> MemoryEntry:
    """从 Markdown 文本(含 frontmatter)解析出 MemoryEntry。

    Raises:
        MemoryParseError: frontmatter 缺失、非 dict、或字段值非法。
    """
    match = _FM_RE.match(text)
    if not match:
        raise MemoryParseError(
            "无法解析 frontmatter: 需要 '---\\n<yaml>\\n---' 包裹的开头"
        )
    raw = yaml.safe_load(match.group(1)) or {}
    if not isinstance(raw, dict):
        raise MemoryParseError("frontmatter 必须是 YAML 键值对映射")

    body = match.group(2).strip()
    expires_raw = raw.get("expires")
    expires = str(expires_raw).strip() if expires_raw else None
    superseded_raw = raw.get("superseded_by")
    superseded_by = str(superseded_raw).strip() if superseded_raw else None

    try:
        return MemoryEntry(
            id=str(raw.get("id", "")).strip(),
            type=MemoryType(str(raw.get("type", ""))),
            title=_extract_title(body),
            scope=MemoryScope(str(raw.get("scope", "team"))),
            author=str(raw.get("author", "")).strip(),
            source=str(raw.get("source", "")).strip(),
            role=str(raw.get("role", "")).strip(),
            created=str(raw.get("created", "")).strip(),
            updated=str(raw.get("updated", "")).strip()
            or str(raw.get("created", "")).strip(),
            expires=expires,
            status=MemoryStatus(str(raw.get("status", "active"))),
            superseded_by=superseded_by,
            tags=tuple(str(t) for t in (raw.get("tags") or [])),
            related=tuple(str(r) for r in (raw.get("related") or [])),
            evidence=tuple(str(e) for e in (raw.get("evidence") or [])),
            confidence=str(raw.get("confidence", "")).strip(),
            body=body,
        )
    except ValueError as exc:
        raise MemoryParseError(f"字段值非法: {exc}") from exc


def serialize_memory(entry: MemoryEntry) -> str:
    """把 MemoryEntry 序列化为 Markdown 文本(含 frontmatter)。"""
    data = entry.to_frontmatter_dict()
    yaml_text = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,  # 避免长行被折叠换行
    ).strip()

    body = entry.body.strip()
    if body:
        return f"---\n{yaml_text}\n---\n\n{body}\n"
    # body 为空时至少补一个标题行
    title = entry.title.strip() or "未命名记忆"
    return f"---\n{yaml_text}\n---\n\n# {title}\n"


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


def validate_entry(entry: MemoryEntry) -> list[str]:
    """返回校验错误列表; 空列表表示通过。"""
    errors: list[str] = []
    for field_name in _REQUIRED_FIELDS:
        value = getattr(entry, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"缺少必填字段: {field_name}")

    if not MEMORY_ID_PATTERN.match(entry.id):
        errors.append(f"id 格式非法(应为 mem-YYYYMMDD-NNN): {entry.id!r}")

    if not entry.title.strip():
        errors.append("缺少标题(body 需以 '# 标题' 开头)")

    if entry.status is MemoryStatus.SUPERSEDED and not entry.superseded_by:
        errors.append("status=superseded 时必须填写 superseded_by")

    return errors
