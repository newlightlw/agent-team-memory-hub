"""Interactive local configuration only. Does not publish, confirm, or send messages."""
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .config import Settings


def atomic_private(path: Path, text: str):
    fd, name = tempfile.mkstemp(prefix=".collab-config-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def configure_feishu(config: Path):
    if not sys.stdin.isatty():
        raise ValueError("Feishu identity configuration requires the person's interactive terminal")
    data = json.loads(config.read_text())
    Settings.load(config)
    print("只更新本机配置；不发布飞书应用、不发送消息、不代替成员确认。空输入保留已有值。")
    for key, prefix in (("app_id", "cli_"), ("chat_id", "oc_")):
        value = input(f"{key} [{data.get(key, '')}]: ").strip() or data.get(key, "")
        if not re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9]+", value):
            raise ValueError("invalid Feishu application or group ID")
        data[key] = value
    for member in data["members"]:
        if not member.get("active", True):
            continue
        print("成员代号：" + member["id"] + "（必须由对应本人确认）")
        member["name"] = input(f"显示名 [{member['name']}]: ").strip() or member["name"]
        value = input(f"同一飞书应用下的 open_id [{member.get('open_id', '')}]: ").strip() or member.get("open_id", "")
        if not re.fullmatch(r"ou_[A-Za-z0-9]+", value):
            raise ValueError("invalid member open_id")
        member["open_id"] = value
    bound_ids = [m["open_id"] for m in data["members"] if m.get("open_id")]
    if len(set(bound_ids)) != len(bound_ids):
        raise ValueError("members must have distinct Feishu identities")
    env_path = config.parent / "secrets.env"
    env = dict(line.split("=", 1) for line in env_path.read_text().splitlines() if "=" in line) if env_path.exists() else {}
    for key in ("COLLAB_FEISHU_APP_SECRET", "COLLAB_FEISHU_VERIFICATION_TOKEN", "COLLAB_FEISHU_ENCRYPT_KEY"):
        value = getpass.getpass(key + "（不回显，空输入保留）：") or env.get(key, "")
        if not value or "\n" in value or "\r" in value:
            raise ValueError("missing or invalid secret")
        env[key] = value
    # Keep a private local backup. No publisher credential is read by this wizard.
    backup = config.with_name("config.before-feishu.json")
    if not backup.exists():
        atomic_private(backup, config.read_text())
    atomic_private(env_path, "".join(f"{k}={v}\n" for k, v in env.items()))
    atomic_private(config, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    Settings.load(config)
    print("配置已保存（权限600）。重启服务并运行 check；配置就绪不代表飞书真实验收通过。")
