"""models.py 的单元测试 — frontmatter 解析/序列化/校验。"""

import pytest

from team_memory.models import (
    MemoryEntry,
    MemoryParseError,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    author_slug,
    format_memory_id,
    memory_id_author,
    memory_id_date,
    parse_memory,
    serialize_memory,
    today_compact,
    today_iso,
    validate_entry,
)


def make_entry(**kwargs):
    base = dict(
        id="mem-20260623-alice-001",
        type=MemoryType.DECISION,
        title="测试",
        author="alice",
        created="2026-06-23",
        body="# 测试\n\n## Context\nhi",
    )
    base.update(kwargs)
    return MemoryEntry(**base)


def test_round_trip():
    entry = make_entry(tags=("a", "b"), related=("mem-20260623-002",))
    text = serialize_memory(entry)
    back = parse_memory(text)
    assert back.id == entry.id
    assert back.type is MemoryType.DECISION
    assert back.scope is MemoryScope.TEAM
    assert back.title == "测试"
    assert back.tags == ("a", "b")
    assert back.related == ("mem-20260623-002",)
    assert back.body.startswith("# 测试")


def test_parse_no_frontmatter_raises():
    with pytest.raises(MemoryParseError):
        parse_memory("没有 frontmatter 的纯文本")


def test_chinese_not_escaped():
    entry = make_entry(title="纯中文标题", body="# 纯中文标题\n\n内容")
    text = serialize_memory(entry)
    assert "纯中文标题" in text  # allow_unicode 生效, 未被转成 \uXXXX


def test_validate_passes_for_valid_entry():
    assert validate_entry(make_entry()) == []


def test_validate_missing_required_and_bad_id():
    entry = MemoryEntry(id="bad-id", type=MemoryType.DECISION, title="x")
    errors = validate_entry(entry)
    assert any("author" in e for e in errors)
    assert any("id 格式" in e for e in errors)


def test_validate_superseded_requires_target():
    entry = make_entry(status=MemoryStatus.SUPERSEDED)
    errors = validate_entry(entry)
    assert any("superseded_by" in e for e in errors)


def test_id_helpers():
    assert format_memory_id("20260623", "alice", 1) == "mem-20260623-alice-001"
    assert format_memory_id("20260623", "alice", 42) == "mem-20260623-alice-042"
    assert memory_id_date("mem-20260623-alice-042") == "20260623"
    assert memory_id_author("mem-20260623-alice-042") == "alice"
    assert memory_id_date("bad") is None
    assert author_slug("Alice Zhang") == "alicezhang"
    assert author_slug("张三") == ""


def test_today_formats():
    assert len(today_compact()) == 8
    assert today_iso().count("-") == 2


def test_source_field_round_trip():
    entry = make_entry(source="codex")
    text = serialize_memory(entry)
    assert "source: codex" in text
    back = parse_memory(text)
    assert back.source == "codex"


def test_source_optional_empty_not_serialized():
    """source 为空时不输出该字段(向后兼容老记忆)。"""
    entry = make_entry()
    text = serialize_memory(entry)
    assert "source:" not in text
    assert parse_memory(text).source == ""
