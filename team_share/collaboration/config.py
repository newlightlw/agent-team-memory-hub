from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    open_id: str
    token_hash: str
    reader_token_hash: str
    active: bool = True


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    members: tuple[Member, ...]
    team_id: str = "duo"
    chat_id: str = ""
    app_id: str = ""
    app_secret: str = field(default="", repr=False)
    verification_token: str = field(default="", repr=False)
    encrypt_key: str = field(default="", repr=False)
    mem0_key: str = field(default="", repr=False)
    mem0_enabled: bool = False
    digest_enabled: bool = False
    digest_hour: int = 20
    config_version: int = 1
    source_path: Path | None = field(default=None, repr=False, compare=False)
    confirmation_enabled: bool = True

    def __post_init__(self):
        if self.config_version not in (1, 2):
            raise ValueError("unsupported config_version")
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", self.team_id):
            raise ValueError("team_id must be a short lowercase ASCII slug")
        if not 2 <= len(self.members) <= 10 or len({m.id for m in self.members}) != len(self.members):
            raise ValueError("require 2–10 distinct members")
        if not all(re.fullmatch(r"[a-z0-9_]{1,32}", m.id) for m in self.members):
            raise ValueError("member IDs must be short lowercase ASCII slugs")
        hashes = [h for m in self.members for h in (m.token_hash, m.reader_token_hash)]
        if len(set(hashes)) != 2 * len(self.members) or not all(re.fullmatch(r"[a-f0-9]{64}", h) for h in hashes):
            raise ValueError("distinct SHA256 credential hashes required")
        ids = [m.open_id for m in self.members if m.open_id]
        if len(ids) != len(set(ids)):
            raise ValueError("Feishu identities must be distinct")
        if self.mem0_enabled and not self.mem0_key:
            raise ValueError("Mem0 explicitly enabled without key")
        if not 0 <= self.digest_hour <= 23:
            raise ValueError("digest_hour must be 0..23")

    @classmethod
    def load(cls, path: Path) -> Settings:
        data = json.loads(path.read_text())
        return cls(
            data_dir=Path(data["data_dir"]).expanduser().resolve(),
            members=tuple(Member(**m) for m in data["members"]),
            team_id=data.get("team_id", "duo"),
            chat_id=data.get("chat_id", ""),
            app_id=data.get("app_id", ""),
            app_secret=os.environ.get("COLLAB_FEISHU_APP_SECRET", ""),
            verification_token=os.environ.get("COLLAB_FEISHU_VERIFICATION_TOKEN", ""),
            encrypt_key=os.environ.get("COLLAB_FEISHU_ENCRYPT_KEY", ""),
            mem0_key=os.environ.get("COLLAB_MEM0_API_KEY", ""),
            mem0_enabled=data.get("mem0_enabled", False),
            digest_enabled=data.get("digest_enabled", False),
            digest_hour=data.get("digest_hour", 20),
            config_version=data.get("config_version", 1),
            source_path=path,
            confirmation_enabled=data.get("confirmation_enabled", len(data["members"]) == 2),
        )

    def identify(self, token: str) -> tuple[Member, str] | None:
        import hmac
        digest = hashlib.sha256(token.encode()).hexdigest()
        for member in self.members:
            if not member.active:
                continue
            if hmac.compare_digest(digest, member.token_hash):
                return member, "publisher"
            if hmac.compare_digest(digest, member.reader_token_hash):
                return member, "reader"
        return None

    def feishu_member(self, open_id: str) -> Member:
        for member in self.members:
            if member.active and member.open_id and member.open_id == open_id:
                return member
        raise PermissionError("unknown Feishu member")
