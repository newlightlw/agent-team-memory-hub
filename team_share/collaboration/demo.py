"""Synthetic, loopback-only demo. No Feishu, model, publisher file or real confirmation."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

import httpx
import uvicorn

from .__main__ import init
from .api import create_app
from .config import Settings
from .projection import export
from .service import Collaboration


def run(*, smoke=False, port=0):
    with tempfile.TemporaryDirectory(prefix="team-share-demo-") as directory:
        root = Path(directory) / "instance"
        with redirect_stdout(StringIO()):
            init(root, ["alice", "bob"])
        settings = Settings.load(root / "config.json")
        service = Collaboration(settings)
        topic = service.create(settings.members[0], dict(kind="topic", title="DEMO_ONLY: shared release question", body="Synthetic topic for learning, not a real team position.", project="demo"))
        share = service.create(settings.members[1], dict(kind="share", title="DEMO_ONLY: Bob's example", body="LANTERN uses explicit human confirmation.", project="demo", topic_id=topic["id"]))
        decision = service.create(settings.members[0], dict(kind="decision", title="DEMO_ONLY: unconfirmed proposal", body="Synthetic proposal; neither person has confirmed.", project="demo", parents=[share["id"]]))
        projection = export(service.store)
        config = uvicorn.Config(create_app(settings, run_worker=False), host="127.0.0.1", port=port, log_level="error", access_log=False)
        server = uvicorn.Server(config)
        sock = socket.socket()
        sock.bind(("127.0.0.1", port))
        base = "http://127.0.0.1:" + str(sock.getsockname()[1])
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            reader = json.loads((root / "alice-reader.json").read_text())
            with httpx.Client(base_url=base, trust_env=False, headers={"Authorization": "Bearer " + reader["token"]}) as client:
                response = client.get("/api/search", params={"q": "LANTERN"})
                assert response.status_code == 200 and share["id"] in response.text
                detail = client.get("/api/records/" + decision["id"]).json()
                assert detail["status"] == "pending_confirmation" and detail["confirmed_by"] == []
                assert client.post("/api/records", json={"kind": "share", "title": "unauthorized", "body": "reader cannot publish"}).status_code == 403
            assert (projection / ".git").is_dir()
            print(json.dumps({"mode": "DEMO_ONLY", "status": "PASS", "http_read": True, "reader_publish_denied": True,
                              "git_projection": True, "real_confirmations": 0, "url": base}))
            if not smoke:
                print("Synthetic demo running on loopback. No real identities or external messaging. Ctrl-C exits and deletes temporary data.")
                while thread.is_alive():
                    time.sleep(.2)
        except KeyboardInterrupt:
            pass
        finally:
            server.should_exit = True
            thread.join(10)
            sock.close()
            if thread.is_alive():
                raise RuntimeError("demo server did not stop")
