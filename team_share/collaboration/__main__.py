from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from .config import Settings


def load_secrets(config):
    path = config.parent / "secrets.env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("COLLAB_") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


def init(root, member_ids):
    if root.exists():
        raise ValueError("initialization requires a new directory")
    if not 2 <= len(member_ids) <= 10 or len(set(member_ids)) != len(member_ids) or not all(
        re.fullmatch(r"[a-z0-9_]{1,32}", m) for m in member_ids
    ):
        raise ValueError("provide 2–10 distinct lowercase ASCII member IDs")
    root.mkdir(mode=0o700, parents=True)
    members = []
    for member_id in member_ids:
        publisher, reader = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        members.append(dict(id=member_id, name=member_id, open_id="",
            token_hash=hashlib.sha256(publisher.encode()).hexdigest(),
            reader_token_hash=hashlib.sha256(reader.encode()).hexdigest()))
        for name, token in (("publisher", publisher), ("reader", reader)):
            path = root / f"{member_id}-{name}.json"
            path.write_text(json.dumps({"url": "http://127.0.0.1:8791", "token": token}, indent=2))
            path.chmod(0o600)
    config = dict(config_version=2, data_dir=str(root / "data"), team_id="team", chat_id="", app_id="",
                  mem0_enabled=False, digest_enabled=False, digest_hour=20, members=members)
    # Validate before any service is launched.
    path = root / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    env = root / "secrets.env"
    env.write_text("COLLAB_BACKUP_KEY=" + Fernet.generate_key().decode() + "\n" +
                   "COLLAB_FEISHU_APP_SECRET=\nCOLLAB_FEISHU_VERIFICATION_TOKEN=\nCOLLAB_FEISHU_ENCRYPT_KEY=\nCOLLAB_MEM0_API_KEY=\n")
    env.chmod(0o600)
    Settings.load(path)
    print(f"已初始化 {path}；身份尚未绑定飞书；凭证文件请分别私下交给本人。")


def main():
    parser = argparse.ArgumentParser(prog="team-collab")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("root", type=Path)
    p.add_argument("--members", nargs="+", default=["alice", "bob"])
    p = sub.add_parser("demo")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--port", type=int, default=0)
    p = sub.add_parser("git-lab")
    p.add_argument("destination", type=Path)
    p = sub.add_parser("configure-feishu")
    p.add_argument("--config", required=True, type=Path)
    p = sub.add_parser("serve")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--port", type=int, default=8791)
    p = sub.add_parser("publish")
    p.add_argument("candidate", type=Path)
    p.add_argument("--credentials", type=Path, default=Path("~/.config/team-collab/publisher.json"))
    for command in ("backup", "restore", "export", "check", "reindex"):
        p = sub.add_parser(command)
        p.add_argument("--config", required=True, type=Path)
        if command == "restore":
            p.add_argument("archive", type=Path)
            p.add_argument("destination", type=Path)
    sub.add_parser("mcp")
    args = parser.parse_args()
    try:
        if args.command == "init":
            init(args.root.expanduser().resolve(), args.members)
        elif args.command == "demo":
            from .demo import run
            run(smoke=args.smoke, port=args.port)
        elif args.command == "git-lab":
            from .git_lab import run
            print(json.dumps(run(args.destination), ensure_ascii=False))
        elif args.command == "configure-feishu":
            from .onboarding import configure_feishu
            configure_feishu(args.config.expanduser().resolve())
        elif args.command == "mcp":
            from .mcp import main as run_mcp
            run_mcp()
        elif args.command == "publish":
            from .api import RecordInput
            from .client import request
            payload = RecordInput(**json.loads(args.candidate.read_text())).model_dump()
            if not sys.stdin.isatty():
                raise ValueError("publish requires a person's interactive terminal")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            if input("以上内容将共享给伙伴。输入 SHARE 确认：") != "SHARE":
                print("未上传；候选保留在本地。")
                return
            credentials = json.loads(args.credentials.expanduser().read_text())
            result = request(credentials["url"], credentials["token"], "POST", "/api/records", payload=payload)
            print("已共享：" + result["id"])
        else:
            config = args.config.expanduser().resolve()
            load_secrets(config)
            settings = Settings.load(config)
            if args.command == "serve":
                import uvicorn
                from .api import create_app
                uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port,
                            workers=1, access_log=False)
            elif args.command == "check":
                from .store import Store
                store = Store(settings.data_dir)
                print(json.dumps({"config_valid": True, "members": [m.id for m in settings.members],
                    "feishu_ready": bool(settings.chat_id and settings.app_id and settings.app_secret and
                                         settings.verification_token and settings.encrypt_key and
                                         all(m.open_id for m in settings.members)),
                    "mem0_enabled": settings.mem0_enabled,
                    "digest_enabled": settings.digest_enabled,
                    "pending_jobs": sum(j["state"] != "done" for j in store.jobs())}, ensure_ascii=False))
            elif args.command == "reindex":
                from .store import Store
                store = Store(settings.data_dir)
                with store.transaction() as db:
                    for item in store.all(history=True):
                        store.enqueue(db, "index", item["id"])
                print("共享记录已排队重新索引；是否完成请查询 /api/jobs。")
            elif args.command == "backup":
                from .backup import backup
                from .store import Store
                key = os.environ.get("COLLAB_BACKUP_KEY")
                if not key:
                    raise ValueError("COLLAB_BACKUP_KEY is required")
                path = backup(Store(settings.data_dir), settings.data_dir / "backups", key)
                print(path)
            elif args.command == "restore":
                from .backup import restore
                restore(args.archive, args.destination, os.environ["COLLAB_BACKUP_KEY"])
                print("已恢复到新目录并通过 integrity_check；未启动服务或发送消息。")
            elif args.command == "export":
                from .projection import export
                from .store import Store
                print(export(Store(settings.data_dir)))
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        print(f"操作未完成：{type(exc).__name__}（请检查配置、权限及服务状态）", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
