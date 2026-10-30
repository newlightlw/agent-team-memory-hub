"""Structured, explicitly enabled GitHub uploads. No team-service publisher token."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .models import MemoryEntry, MemoryType, MemoryStatus, serialize_memory

FIELDS = {
    "purpose": "目的与背景",
    "process": "关键过程与取舍",
    "results": "关键结果与验证",
    "insights": "核心思想",
    "applications": "未来应用与触发条件",
    "discussions": "讨论、分歧与待解决问题",
}


def redact_credentials(text):
    """Remove common credential literals; preserve all other original context."""
    text = re.sub(r"\b(?:ghp_|gho_|github_pat_|sk-)[A-Za-z0-9_-]{16,}", "[credential redacted]", text)
    text = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{16,}=*", r"\1[credential redacted]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|app[_-]?secret|access[_-]?token|password)[\"']?\s*[=:]\s*[\"']?)[A-Za-z0-9._~+/-]{12,}", r"\1[credential redacted]", text)
    return re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[credential redacted]@", text)


def validate_summary(summary):
    if not isinstance(summary, dict) or set(summary) != set(FIELDS):
        raise ValueError("Summary requires exactly: " + ", ".join(FIELDS))
    for key in FIELDS:
        if not isinstance(summary[key], str) or not summary[key].strip() or len(summary[key]) > 20000:
            raise ValueError("Each summary field must be nonempty and bounded; use 未提及 when absent")
    return summary


def render_archive(title, summary, *, author, source, source_refs, original="", source_status="individual_record"):
    validate_summary(summary)
    if not title.strip() or len(title) > 200 or not source.strip() or len(source) > 200:
        raise ValueError("Supply bounded title and source tool")
    if not re.fullmatch(r"[a-z0-9_]{1,32}", author):
        raise ValueError("Invalid configured author")
    if not isinstance(source_refs, list) or not 1 <= len(source_refs) <= 50 or any(
        not isinstance(x, str) or not x.strip() or len(x) > 2000 for x in source_refs
    ):
        raise ValueError("Supply 1–50 source references (chat/topic/file/message IDs or URLs)")
    if len(original) > 100000:
        raise ValueError("Original exceeds record budget; split explicitly, never silently truncate")
    body = f"# {title}\n\n作者：{author}\n\n来源工具：{source}\n\n来源状态：{source_status}（自动归档不代表团队共识）\n"
    for field, heading in FIELDS.items():
        body += f"\n## {heading}\n\n{summary[field].strip()}\n"
    body += "\n## 来源与证据\n\n" + "\n".join("- " + ref for ref in source_refs) + "\n"
    if original:
        body += "\n## 原始资料（来源数据）\n\n" + original + "\n"
    body = redact_credentials(body)
    if len(body.encode("utf-8")) > 240000:
        raise ValueError("Archive exceeds readable Git blob budget; split selected material explicitly")
    return body


class GitHubArchive:
    """One file per stable request key; optimistic Contents API, no blanket git add."""
    def __init__(self, repo, *, branch="main", enabled=False, gh="gh"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
            raise ValueError("Configure GitHub OWNER/REPO")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,160}", branch) or ".." in branch:
            raise ValueError("Invalid branch")
        self.repo, self.branch, self.enabled, self.gh = repo, branch, enabled, gh

    def api(self, path, *, method="GET", payload=None, missing_ok=False):
        args = [self.gh, "api", "--hostname", "github.com", "--method", method, path]
        if payload is not None:
            args += ["--input", "-"]
        result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                                capture_output=True, text=True, timeout=45)
        if result.returncode:
            if missing_ok and "(HTTP 404)" in result.stderr:
                return None
            # Do not echo private content, credential-helper errors or response bodies.
            raise RuntimeError("GitHub request failed; upload unconfirmed, retry with the SAME request_id")
        return json.loads(result.stdout)

    def publish(self, *, request_id, title, body, author, source, date=None, deprecated=False):
        if not self.enabled:
            raise ValueError("Uploads disabled; enable explicitly in member installation/config")
        body = redact_credentials(body)
        title = redact_credentials(title)
        if not request_id.strip() or len(request_id) > 500:
            raise ValueError("A stable bounded request_id is required")
        # Never send private records to a public repository, even after a visibility change.
        if self.api("repos/" + self.repo).get("private") is not True:
            raise ValueError("Automatic archives require a PRIVATE data repository")
        digest = hashlib.sha256(request_id.encode()).hexdigest()[:24]
        # Stable across midnight/retries/revisions; source ID lives in the body too.
        path = "memory/project/archive-" + digest + ".md"
        endpoint = f"repos/{self.repo}/contents/{path}"
        from urllib.parse import quote
        for attempt in range(3):
            existing = self.api(endpoint + "?ref=" + quote(self.branch, safe=""), missing_ok=True)
            created = date or datetime.now(timezone.utc).date().isoformat()
            if existing:
                from .models import parse_memory
                old_text = base64.b64decode(existing["content"]).decode()
                old = parse_memory(old_text)
                if old.author != author or old.source != source:
                    raise ValueError("Request ID belongs to another author/source")
                created = old.created
            memory_id = "mem-" + created.replace("-", "") + "-archive_" + digest + "-001"
            entry = MemoryEntry(id=memory_id, type=MemoryType.PROJECT, title=title,
                                author=author, source=source, created=created, updated=created,
                                status=MemoryStatus.DEPRECATED if deprecated else MemoryStatus.ACTIVE,
                                tags=("archive", "individual_record"), body=body)
            text = serialize_memory(entry)
            if existing and old_text == text:
                return {"uploaded": True, "duplicate": True, "id": memory_id,
                        "blob_sha": existing["sha"], "url": existing["html_url"], "path": path}
            payload = {"message": "archive: " + memory_id,
                       "content": base64.b64encode(text.encode()).decode(), "branch": self.branch}
            if existing:
                payload["sha"] = existing["sha"]
            try:
                result = self.api(endpoint, method="PUT", payload=payload)
                return {"uploaded": True, "duplicate": False, "id": memory_id,
                        "commit": result["commit"]["sha"], "url": result["content"]["html_url"], "path": path}
            except RuntimeError:
                # A timeout may occur AFTER GitHub accepted the write. Re-read before retry.
                if attempt == 2:
                    raise
        raise RuntimeError("Upload unconfirmed")


def configured_archive():
    return GitHubArchive(os.environ.get("TEAM_MEMORY_GITHUB_REPO", ""),
                         branch=os.environ.get("TEAM_MEMORY_GITHUB_BRANCH", "main"),
                         enabled=os.environ.get("TEAM_MEMORY_UPLOAD_ENABLED") == "1",
                         gh=os.environ.get("TEAM_MEMORY_GH", "gh"))


def archive_selected(*, title, summary, source_refs, request_id, source, author, original="", writer=None):
    body = render_archive(title, summary, author=author, source=source,
                          source_refs=source_refs, original=original)
    # Durable local retry material before any outward write; never call failed upload a success.
    outbox = Path(os.environ.get("TEAM_MEMORY_OUTBOX", "~/.config/team-memory-hub/outbox")).expanduser()
    if outbox.is_symlink():
        raise ValueError("Outbox must not be a symlink")
    outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(request_id.encode()).hexdigest()
    path = outbox / ("archive-" + key + ".json")
    payload = dict(title=title, body=body, author=author, source=source, request_id=request_id)
    if path.is_symlink():
        raise ValueError("Archive draft must not be a symlink")
    if path.exists():
        old = json.loads(path.read_text())
        if old["payload"] != payload:
            raise ValueError("Request ID reused with different material; use a new ID for a new archive")
    fd, temporary = tempfile.mkstemp(dir=outbox, prefix=".archive-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"payload": payload, "uploaded": False}, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        result = (writer or configured_archive()).publish(**payload)
        path.write_text(json.dumps({"payload": payload, **result}, ensure_ascii=False, indent=2))
        path.chmod(0o600)
        return result
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
