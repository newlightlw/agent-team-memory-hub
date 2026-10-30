"""Poll the authenticated Feishu feed; summarize FIRST, then mirror into private GitHub.
Run with: python -m team_memory.archive_sync --config PRIVATE_CONFIG [--once]
The summary command receives JSON source data on stdin and must return six-field JSON.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import quote
import urllib.request

from .archive import GitHubArchive, render_archive, validate_summary, redact_credentials


def private_json(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Private regular configuration file required")
    return json.loads(path.read_text())


class FeishuArchiveSync:
    def __init__(self, config, *, writer=None, summarize=None):
        self.config = config
        self.state_path = Path(config["state"]).expanduser()
        self.state = private_json(self.state_path) if self.state_path.exists() else {"cursor": "", "records": {}}
        self.writer = writer or GitHubArchive(config["repo"], branch=config.get("branch", "main"), enabled=True, gh=config.get("gh", "gh"))
        self.summarize = summarize or self.command_summary

    def request(self, suffix):
        from urllib.parse import urlsplit
        cfg = private_json(self.config["reader_config"])
        base = cfg["url"].rstrip("/")
        parsed = urlsplit(base)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not (
            parsed.scheme == "https" or parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
        ):
            raise ValueError("Invalid team reader URL")
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError("Reader endpoint redirects disabled")
        request = urllib.request.Request(base + suffix, headers={"Authorization": "Bearer " + cfg["token"]})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            data = response.read(4_000_001)
        if len(data) > 4_000_000:
            raise ValueError("Feed budget exceeded")
        return json.loads(data)

    def command_summary(self, record):
        command = self.config["summary_command"]
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ValueError("summary_command must be an argv list")
        result = subprocess.run(command, input=json.dumps(record, ensure_ascii=False),
                                capture_output=True, text=True, timeout=300)
        if result.returncode or len(result.stdout) > 150000:
            raise RuntimeError("AI summary failed; source NOT uploaded, cursor preserved")
        return validate_summary(json.loads(result.stdout))

    def persist(self):
        from .member_setup import _atomic
        _atomic(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=2))

    def tick(self):
        feed = self.request("/api/archive-feed?limit=20&cursor=" + quote(self.state["cursor"], safe=""))
        count = 0
        for record in feed["records"]:
            rid = record["id"]
            version = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if self.state["records"].get(rid) == version:
                continue
            request_id = "feishu:" + self.config["team_id"] + ":" + rid
            if record["status"] == "withdrawn":
                # Unknown withdrawn rows have never been uploaded; no content to remove.
                if rid not in self.state["records"]:
                    self.state["records"][rid] = version
                    continue
                body = f'# 已撤回\n\n来源 {rid} 已撤回；当前版本不再提供正文或摘要。Git 历史副本仍可能存在。\n'
                result = self.writer.publish(request_id=request_id, title="已撤回", body=body,
                            author=record["author"], source="feishu", date=record["created"][:10], deprecated=True)
            else:
                summary_record = json.loads(redact_credentials(json.dumps(record, ensure_ascii=False)))
                summary = validate_summary(self.summarize(summary_record))
                # Recheck after expensive AI inference to avoid knowingly uploading an old revision.
                current = self.request("/api/records/" + quote(rid, safe=""))
                if any(current[k] != record[k] for k in ("revision", "updated", "status", "body")):
                    raise RuntimeError("Feishu source changed during summary; retry from feed")
                body = render_archive(record["title"], summary, author=record["author"], source="feishu",
                        source_refs=[rid, record["source_url"] or "feishu:archive"], original=record["body"],
                        source_status=record["status"] + "; revision=" + str(record["revision"]))
                result = self.writer.publish(request_id=request_id, title=record["title"], body=body,
                        author=record["author"], source="feishu", date=record["created"][:10])
            if not result.get("uploaded"):
                raise RuntimeError("Upload not confirmed; cursor preserved")
            self.state["records"][rid] = version
            self.persist()
            count += 1
        self.state["cursor"] = feed["next_cursor"]
        self.persist()
        return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    cfg = private_json(args.config)
    if cfg.get("enabled") is not True:
        raise SystemExit("Automatic Feishu uploads not enabled")
    # Avoid overlapping jobs (LaunchAgent or manual run), including AI inference.
    import fcntl
    state = Path(cfg["state"]).expanduser()
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state.parent / (state.name + ".lock")).open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        worker = FeishuArchiveSync(cfg)
        failures = 0
        while True:
            try:
                count = worker.tick()
                failures = 0
                from .member_setup import _atomic
                from datetime import datetime, timezone
                _atomic(state.with_suffix(".status.json"), json.dumps({"ok": True, "last_success": datetime.now(timezone.utc).isoformat(), "uploaded_records": count}))
                print(json.dumps({"uploaded_records": count, "ok": True}), flush=True)
            except Exception as error:
                failures += 1
                from .member_setup import _atomic
                from datetime import datetime, timezone
                status_path = state.with_suffix(".status.json")
                previous = private_json(status_path) if status_path.exists() else {}
                _atomic(status_path, json.dumps({"ok": False, "last_success": previous.get("last_success"), "failed_at": datetime.now(timezone.utc).isoformat(), "error_class": type(error).__name__}))
                print(json.dumps({"ok": False, "error_class": type(error).__name__, "retry": "cursor preserved"}), flush=True)
                if args.once:
                    raise SystemExit(1) from None
            if args.once:
                return
            time.sleep(max(15, cfg.get("interval_seconds", 60)) if not failures else min(900, 60 * 2 ** min(failures, 4)))


if __name__ == "__main__":
    main()
