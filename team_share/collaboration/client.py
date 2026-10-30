from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def request(base: str, token: str, method: str, path: str, *, payload=None):
    parsed = urlparse(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("use HTTPS or a localhost SSH tunnel")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("credentials must not appear in service URL")
    with httpx.Client(base_url=base.rstrip("/"), timeout=20, trust_env=False,
                      headers={"Authorization": f"Bearer {token}"}) as client:
        result = client.request(method, path, json=payload)
    if result.is_error:
        raise RuntimeError(f"gateway returned HTTP {result.status_code}")
    return result.json()


def stage(payload, outbox: Path):
    """Local-only private candidate; this function performs no network I/O."""
    from .api import RecordInput
    validated = RecordInput(**payload).model_dump()
    outbox.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = outbox / (uuid4().hex + ".json")
    path.write_text(json.dumps(validated, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    return path


def reader():
    config_path = Path(os.environ.get("COLLAB_CLIENT_CONFIG", "~/.config/team-collab/reader.json")).expanduser()
    data = json.loads(config_path.read_text())
    return data["url"], data["token"]
