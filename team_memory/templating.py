"""模板渲染辅助 — 把 templates/ 下的模板拷贝并渲染到目标。

变量替换: {name} -> value(仅匹配 \\w+ 标识符, 不影响 markdown 表格 / 花括号)。
未提供的变量保持原样, 便于二次渲染。
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["TEMPLATES_DIR", "render", "copy_template_tree"]

# 工具包自带的模板目录(team_memory/../templates)
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_VAR_RE = re.compile(r"\{(\w+)\}")


def render(text: str, **variables: str) -> str:
    """把 {var} 替换为 variables 中的值; 未提供的变量保持原样。"""

    def repl(match: re.Match[str]) -> str:
        return variables.get(match.group(1), match.group(0))

    return _VAR_RE.sub(repl, text)


def copy_template_tree(
    src: Path,
    dst: Path,
    variables: dict[str, str] | None = None,
    overwrite: bool = False,
) -> list[Path]:
    """递归拷贝 src 模板目录到 dst, 渲染变量。

    已存在的文件默认跳过(除非 overwrite=True)。返回实际写入的文件列表。
    """
    variables = variables or {}
    written: list[Path] = []
    if not src.exists():
        return written
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and not overwrite:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_text(encoding="utf-8")
        target.write_text(render(content, **variables), encoding="utf-8")
        written.append(target)
    return written
