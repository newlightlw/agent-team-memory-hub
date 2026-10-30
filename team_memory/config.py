"""配置加载 — 从 .env 读取 Git remote / 团队 / 作者等配置。

优先级: 真实环境变量 > .env 文件 > dataclass 默认值。
不依赖 python-dotenv, 自带一个极简 .env 解析器。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Config", "load_config", "parse_env_file"]

# 与 .env 中对应的键名
_ENV_KEYS = (
    "REMOTE_URL",
    "GITEA_REMOTE_URL",
    "GITEA_TOKEN",
    "TEAM_NAME",
    "DEFAULT_AUTHOR",
    "DEFAULT_MEMORY_PATH",
    "EXTERNAL_MEMORY_PATH",
    "TEAM_MEMORY_ROOT",
    "WEB_HOST",
    "WEB_PORT",
    "WEB_PUBLIC_URL",
)

# .env.example 占位符里的主机名, 用于判断 remote 是否仍是占位符
_PLACEHOLDER_HOST = "example.com"


def parse_env_file(path: Path) -> dict[str, str]:
    """解析 .env 文件为 dict; 文件不存在返回空 dict。

    支持: 注释(#)、空行、KEY=VALUE、首尾引号去除。
    """
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            data[key] = value
    return data


@dataclass(frozen=True)
class Config:
    """运行配置。不可变。"""

    remote_url: str = ""
    gitea_remote_url: str = ""
    gitea_token: str = field(default="", repr=False)
    team_name: str = "我们的团队"
    default_author: str = ""
    default_memory_path: str = "./memory"
    external_memory_path: str = ""
    web_host: str = "127.0.0.1"
    web_port: int = 8765
    web_public_url: str = ""

    @property
    def has_gitea_remote(self) -> bool:
        """是否配置了非空的 Git remote。"""
        return bool(self.remote_url.strip() or self.gitea_remote_url.strip())

    @property
    def has_external_source(self) -> bool:
        """是否配置了外部 Markdown 记忆源。"""
        return bool(self.external_memory_path.strip())

    @property
    def is_remote_placeholder(self) -> bool:
        """Git remote 是否仍是占位符(未填真实地址)。"""
        return _PLACEHOLDER_HOST in (self.remote_url or self.gitea_remote_url)

    def resolved_remote_url(self) -> str:
        """返回可用于推送的 remote url。

        只返回不含凭证的 URL；HTTPS 使用 Git credential helper，SSH 使用本人密钥。
        """
        from .sharing import validate_remote
        url = self.remote_url.strip() or self.gitea_remote_url.strip()
        if self.gitea_token:
            raise ValueError("GITEA_TOKEN URL injection retired; use git credential helper / gh auth setup-git or SSH")
        if url:
            validate_remote(url)
        return url

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> Config:
        """从 .env + 环境变量加载配置。

        Args:
            env_path: .env 文件路径; None 时用 cwd/.env。
        """
        path = env_path if env_path is not None else Path.cwd() / ".env"
        merged = parse_env_file(path)
        # 真实环境变量优先级最高
        for key in _ENV_KEYS:
            env_value = os.environ.get(key)
            if env_value:
                merged[key] = env_value
        web_port_raw = merged.get("WEB_PORT", "8765").strip()
        try:
            web_port = int(web_port_raw)
        except ValueError:
            web_port = 8765
        return cls(
            remote_url=merged.get("REMOTE_URL", ""),
            gitea_remote_url=merged.get("GITEA_REMOTE_URL", ""),
            gitea_token=merged.get("GITEA_TOKEN", ""),
            team_name=merged.get("TEAM_NAME", "我们的团队"),
            default_author=merged.get("DEFAULT_AUTHOR", ""),
            default_memory_path=merged.get("DEFAULT_MEMORY_PATH", "./memory"),
            external_memory_path=merged.get("EXTERNAL_MEMORY_PATH", ""),
            web_host=merged.get("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
            web_port=web_port,
            web_public_url=merged.get("WEB_PUBLIC_URL", "").strip(),
        )


def load_config(env_path: Path | None = None) -> Config:
    """加载配置的便捷函数。"""
    return Config.from_env(env_path)
