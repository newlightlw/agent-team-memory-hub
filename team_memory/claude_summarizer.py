"""Input-only Claude Code adapter; requires safe-mode and schema output only, no execution tools, fails closed."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from .archive import FIELDS, redact_credentials, validate_summary
from .archive_summarizer import PROMPT

REQUIRED = (
    "--safe-mode",
    "--tools",
    "--strict-mcp-config",
    "--mcp-config",
    "--setting-sources",
    "--no-session-persistence",
    "--disable-slash-commands",
    "--json-schema",
    "--output-format",
)


def probe(binary):
    if not Path(binary).is_absolute() or not Path(binary).is_file():
        raise ValueError("absolute Claude executable required")
    r = subprocess.run(
        [binary, "--help"], check=False, capture_output=True, text=True, timeout=15
    )
    if r.returncode or any(x not in r.stdout for x in REQUIRED):
        raise RuntimeError("Claude lacks required safety flags; adapter disabled")
    return {"compatible_flags": True, "runtime_tool_audit_required": True}


def summarize(record, binary, *, timeout=240):
    probe(binary)
    raw = redact_credentials(json.dumps(record, ensure_ascii=False))
    if len(raw) > 120000:
        raise ValueError("Source budget exceeded")
    schema = {
        "type": "object",
        "properties": {k: {"type": "string"} for k in FIELDS},
        "required": list(FIELDS),
        "additionalProperties": False,
    }
    with tempfile.TemporaryDirectory(prefix="team-memory-claude-summary-") as directory:
        root = Path(directory)
        root.chmod(0o700)
        args = [
            binary,
            "--print",
            "--safe-mode",
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(schema),
        ]
        # Auth remains in the member's own account/keychain. No auth file is copied.
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            in (
                "HOME",
                "USER",
                "PATH",
                "LANG",
                "TMPDIR",
                "HTTPS_PROXY",
                "HTTP_PROXY",
                "ALL_PROXY",
                "NO_PROXY",
                "https_proxy",
                "http_proxy",
                "all_proxy",
                "no_proxy",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
                "ANTHROPIC_API_KEY",
                "CLAUDE_CODE_OAUTH_TOKEN",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                "ANTHROPIC_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_REASONING_MODEL",
            )
        }
        # Safe-mode skips user customizations. Read only known authentication/provider env keys; never hooks, permissions, helpers or plugins.
        settings_path = Path.home() / ".claude/settings.json"
        if settings_path.is_file():
            settings = json.loads(settings_path.read_text())
            allowed = {
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                "ANTHROPIC_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_REASONING_MODEL",
            }
            for key, value in settings.get("env", {}).items():
                if key in allowed and isinstance(value, str):
                    env.setdefault(key, value)
        env.update(
            {
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_TELEMETRY": "1",
                "CLAUDE_CODE_SAFE_MODE": "1",
            }
        )
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=root,
            env=env,
            start_new_session=True,
        )
        import threading

        previous = None

        def stop():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        def terminated(signum, frame):
            stop()
            raise SystemExit(128 + signum)

        if threading.current_thread() is threading.main_thread():
            previous = signal.signal(signal.SIGTERM, terminated)
        try:
            try:
                out, _ = proc.communicate(PROMPT + raw, timeout=timeout)
            except subprocess.TimeoutExpired:
                stop()
                proc.communicate()
                raise RuntimeError("Claude summary timeout; no upload") from None
        finally:
            stop()
            proc.wait()
            if previous is not None:
                signal.signal(signal.SIGTERM, previous)
        if proc.returncode or len(out) > 500000:
            raise RuntimeError("Claude summary unavailable; no upload")
        result = None
        observed_init = False
        for line in out.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") == "system" and event.get("subtype") == "init":
                observed_init = True
                if (
                    set(event.get("tools", [])) - {"StructuredOutput"}
                    or event.get("mcp_servers")
                    or event.get("plugins")
                    or event.get("skills")
                ):
                    raise RuntimeError("Claude customizations/tools active; no upload")
            content = event.get("message", {}).get("content", [])
            if any(
                x.get("type") in ("tool_use", "server_tool_use")
                and (x.get("type") != "tool_use" or x.get("name") != "StructuredOutput")
                for x in content
                if isinstance(x, dict)
            ):
                raise RuntimeError("Claude tool activity rejected; no upload")
            if event.get("type") == "result":
                result = event
        if (
            not observed_init
            or not result
            or result.get("is_error")
            or result.get("subtype") != "success"
        ):
            raise RuntimeError("Claude audit/result incomplete; no upload")
        return validate_summary(result.get("structured_output"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--claude", required=True)
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    try:
        if a.check:
            result = probe(a.claude)
        else:
            raw = sys.stdin.read(120001)
            if len(raw) > 120000:
                raise ValueError("input budget exceeded")
            result = summarize(json.loads(raw), a.claude)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as e:
        print(
            "Claude summary failed: " + type(e).__name__ + "; no upload",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
