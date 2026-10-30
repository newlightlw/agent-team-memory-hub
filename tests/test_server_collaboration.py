import base64
import hashlib
import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient

from team_share.collaboration.api import create_app
from team_share.collaboration.backup import backup, restore
from team_share.collaboration.client import stage
from team_share.collaboration.config import Member, Settings
from team_share.collaboration.integrations import Feishu, Mem0
from team_share.collaboration.projection import export, git
from team_share.collaboration.service import Collaboration
from team_share.collaboration.worker import Worker
from team_share.store import MemoryStore


def hashed(s):
    return hashlib.sha256(s.encode()).hexdigest()


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "data", (
        Member("alice", "Alice", "ou_alice", hashed("alice-pub"), hashed("alice-read")),
        Member("bob", "Bob", "ou_bob", hashed("bob-pub"), hashed("bob-read")),
    ), chat_id="oc_team", app_id="cli_app", app_secret="secret", verification_token="verify", encrypt_key="encrypt")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, run_worker=False)) as c:
        yield c


def auth(who="alice", role="pub"):
    return {"Authorization": f"Bearer {who}-{role}"}


def record(client, **kwargs):
    payload = dict(kind="share", title="产品判断", body="需要验证用户痛点", project="pilot")
    payload.update(kwargs)
    result = client.post("/api/records", json=payload, headers=auth())
    assert result.status_code == 201, result.text
    return result.json()


def signed(settings, body, *, encrypted=False, stamp=None):
    raw = json.dumps(body).encode()
    if encrypted:
        iv = os.urandom(16)
        padder = padding.PKCS7(128).padder()
        padded = padder.update(raw) + padder.finalize()
        encryptor = Cipher(algorithms.AES(hashlib.sha256(settings.encrypt_key.encode()).digest()), modes.CBC(iv)).encryptor()
        raw = json.dumps({"encrypt": base64.b64encode(iv + encryptor.update(padded) + encryptor.finalize()).decode()}).encode()
    stamp = str(int(time.time()) if stamp is None else stamp)
    nonce = "nonce"
    digest = hashlib.sha256((stamp + nonce + settings.encrypt_key).encode() + raw).hexdigest()
    return raw, {"Content-Type": "application/json", "x-lark-request-timestamp": stamp,
                 "x-lark-request-nonce": nonce, "x-lark-signature": digest}


def callback(client, settings, body, **kwargs):
    raw, headers = signed(settings, body, **kwargs)
    return client.post("/feishu/events", content=raw, headers=headers)


def message(settings, text="不同意原判断，先访谈", mid="om_1", group="oc_team", user="ou_bob"):
    return {"schema": "2.0", "header": {"event_id": mid, "event_type": "im.message.receive_v1",
        "app_id": settings.app_id, "token": settings.verification_token}, "event": {
        "sender": {"sender_type": "user", "sender_id": {"open_id": user}},
        "message": {"message_id": mid, "chat_id": group, "message_type": "text", "create_time": "123",
                    "content": json.dumps({"text": text})}}}


def vote(settings, rid, user="ou_alice", revision=1):
    return {"schema": "2.0", "header": {"event_id": "vote-" + user, "event_type": "card.action.trigger",
        "app_id": settings.app_id, "token": settings.verification_token}, "event": {
        "operator": {"open_id": user}, "context": {"open_chat_id": settings.chat_id},
        "action": {"value": {"action": "confirm", "id": rid, "revision": revision}}}}


def test_auth_and_untrusted_author(client):
    assert client.get("/api/briefing").status_code == 401
    assert client.get("/api/briefing", headers=auth(role="read")).status_code == 200
    assert client.post("/api/records", headers=auth(role="read"), json={"title": "x", "body": "x"}).status_code == 403
    assert client.post("/api/records", headers=auth(), json={"title": "x", "body": "x", "author": "bob"}).status_code == 422
    item = record(client)
    assert item["author"] == "alice"
    assert client.delete("/api/records/" + item["id"], headers=auth("bob")).status_code == 403


def test_payload_bound(client):
    response = client.post("/api/records", content=b"a" * 256001, headers=auth())
    assert response.status_code == 413
    assert client.get("/healthz").headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("encrypted", [False, True])
def test_feishu_ingest_idempotency_and_search(client, settings, encrypted):
    body = message(settings)
    first = callback(client, settings, body, encrypted=encrypted)
    assert first.status_code == 200, first.text
    second = callback(client, settings, body, encrypted=encrypted)
    assert first.json()["id"] == second.json()["id"]
    result = client.get("/api/search?q=不同意", headers=auth(role="read")).json()["results"]
    assert len(result) == 1 and result[0]["author"] == "bob"
    assert result[0]["source_url"].startswith("feishu:")


def test_feishu_reject_bad_signature_expired_and_wrong_app(client, settings):
    raw, headers = signed(settings, message(settings))
    headers["x-lark-signature"] = "fake"
    assert client.post("/feishu/events", content=raw, headers=headers).status_code == 403
    assert callback(client, settings, message(settings), stamp=1).status_code == 403
    body = message(settings)
    body["header"]["app_id"] = "someone-else"
    assert callback(client, settings, body).status_code == 403
    assert callback(client, settings, message(settings, group="oc_other")).json()["ignored"]
    assert callback(client, settings, message(settings, user="stranger")).json()["ignored"]


def test_challenge_cannot_mutate(client, settings):
    body = {"type": "url_verification", "token": settings.verification_token, "challenge": "hello"}
    assert callback(client, settings, body).json() == {"challenge": "hello"}
    assert client.get("/api/search?q=hello", headers=auth()).json()["results"] == []


def test_two_actual_members_required_and_agents_cannot_vote(client, settings):
    source = record(client)
    decision = record(client, kind="decision", title="先访谈再开发", parents=[source["id"]])
    rid = decision["id"]
    assert decision["status"] == "pending_confirmation"
    assert client.post(f"/api/records/{rid}/confirm", headers=auth(), json={}).status_code == 404
    assert callback(client, settings, vote(settings, rid)).status_code == 200
    callback(client, settings, vote(settings, rid))
    got = client.get(f"/api/records/{rid}", headers=auth()).json()
    assert got["status"] == "pending_confirmation" and got["confirmed_by"] == ["alice"]
    assert callback(client, settings, vote(settings, rid, "unknown")).status_code == 403
    assert callback(client, settings, vote(settings, rid, "ou_bob")).status_code == 200
    got = client.get(f"/api/records/{rid}", headers=auth()).json()
    assert got["status"] == "active" and set(got["confirmed_by"]) == {"alice", "bob"}


def test_changed_decision_invalidates_old_card_and_votes(client, settings):
    source = record(client)
    decision = record(client, kind="decision", parents=[source["id"]])
    rid = decision["id"]
    callback(client, settings, vote(settings, rid))
    payload = {"revision": 1, "title": "修改后的判断", "body": "先做十次访谈"}
    assert client.put(f"/api/records/{rid}", headers=auth(), json=payload).status_code == 200
    assert callback(client, settings, vote(settings, rid, "ou_bob")).status_code == 409
    callback(client, settings, vote(settings, rid, "ou_bob", 2))
    assert client.get(f"/api/records/{rid}", headers=auth()).json()["status"] == "pending_confirmation"
    callback(client, settings, vote(settings, rid, "ou_alice", 2))
    assert client.get(f"/api/records/{rid}", headers=auth()).json()["status"] == "active"
    assert client.put(f"/api/records/{rid}", headers=auth(), json={**payload, "revision": 2}).status_code == 409


def test_replacement_requires_consensus_and_history_survives(client, settings):
    source = record(client)
    old = record(client, kind="decision", title="旧判断", parents=[source["id"]])
    for user in ("ou_alice", "ou_bob"):
        callback(client, settings, vote(settings, old["id"], user))
    new = record(client, kind="decision", title="新判断", parents=[source["id"]], data={"replaces": old["id"]})
    assert client.get(f'/api/records/{old["id"]}', headers=auth()).json()["status"] == "active"
    for user in ("ou_alice", "ou_bob"):
        callback(client, settings, vote(settings, new["id"], user))
    assert client.get(f'/api/records/{old["id"]}', headers=auth()).json()["status"] == "superseded"
    assert client.get("/api/search?q=旧判断", headers=auth()).json()["results"] == []
    assert client.get("/api/search?q=旧判断&history=true", headers=auth()).json()["results"][0]["replaced_by"] == new["id"]


def test_local_private_candidate_never_uploaded(tmp_path, client):
    path = stage({"title": "私人秘密", "body": "仅本地候选"}, tmp_path / "outbox")
    assert path.stat().st_mode & 0o777 == 0o600
    assert client.get("/api/search?q=私人秘密", headers=auth("bob")).json()["results"] == []


def test_topic_viewpoints_experiment_and_source_chain(client):
    share = record(client)
    topic = record(client, kind="topic", title="是否值得做", parents=[share["id"]],
                   data={"disagreements": "alice 希望原型；bob 希望先访谈", "next_validation": "访谈两名目标用户"})
    assert "question" in topic["data"]
    got = client.get(f'/api/records/{topic["id"]}?history=true', headers=auth()).json()
    assert got["parents"] == [share["id"]]
    exp = record(client, kind="experiment", parents=[topic["id"]],
                 data={"owner": "bob", "expected_observation": "愿意试用", "review_date": "2026-11-01"})
    assert exp["data"]["outcome"] == "unverified"
    assert len(client.get("/api/briefing?project=pilot", headers=auth()).json()["experiments"]) == 1
    assert client.post("/api/records", headers=auth(), json={"kind": "experiment", "title": "x", "body": "x"}).status_code == 409


def test_cycles_and_optimistic_lock(client):
    source = record(client)
    topic = record(client, kind="topic", parents=[source["id"]])
    payload = {"revision": 1, "title": "x", "body": "x", "parents": [topic["id"]]}
    assert client.put(f'/api/records/{source["id"]}', headers=auth(), json=payload).status_code == 409
    assert client.get(f'/api/records/{source["id"]}', headers=auth()).json()["revision"] == 1
    payload["parents"] = []
    assert client.put(f'/api/records/{source["id"]}', headers=auth(), json=payload).status_code == 200
    assert client.put(f'/api/records/{source["id"]}', headers=auth(), json=payload).status_code == 409


def test_withdrawal_scrubs_descendants_history_git_and_stale_index(client, settings, monkeypatch):
    share = record(client, body="sensitive-original")
    topic = record(client, kind="topic", title="sensitive-derived", parents=[share["id"]])
    service = client.app.state.service
    root = export(service.store)
    assert "sensitive-derived" in git(root, "log", "-p")
    class StaleIndex:
        def search(self, q): return [topic["id"], share["id"]]
        def delete(self, rid): pass
    client.app.state.semantic = StaleIndex()
    assert client.delete(f'/api/records/{share["id"]}', headers=auth()).status_code == 200
    assert client.get("/api/search?q=sensitive", headers=auth()).json()["results"] == []
    got = client.get(f'/api/records/{topic["id"]}?history=true', headers=auth()).json()
    assert got["body"] == "" and got["history"][0]["title"] == "[已撤回]"
    worker = Worker(service, semantic=StaleIndex())
    for _ in range(30):
        if not worker.tick(): break
    assert "sensitive-derived" not in git(root, "log", "-p")
    assert not any(j["state"] != "done" for j in service.store.jobs())


def test_mem0_outage_keeps_keyword_results(client):
    record(client)
    class Broken:
        def search(self, q): raise RuntimeError("provider down")
    client.app.state.semantic = Broken()
    result = client.get("/api/search?q=产品", headers=auth()).json()
    assert result["mode"] == "keyword_fallback" and len(result["results"]) == 1


def test_durable_retry_no_content_in_error(client):
    item = record(client, body="private-body")
    service = client.app.state.service
    class Broken:
        def index(self, item): raise RuntimeError("private-body echoed by provider")
    worker = Worker(service, semantic=Broken())
    worker.tick()
    job = next(j for j in service.store.jobs() if j["kind"] == "index")
    assert job["attempts"] == 1 and job["state"] == "pending" and job["error"] == "RuntimeError"
    assert service.store.get(item["id"])["body"] == "private-body"
    worker = Worker(Collaboration(service.settings), semantic=Broken())
    assert next(j for j in worker.store.jobs() if j["kind"] == "index")["attempts"] == 1


def test_backup_restore_and_projection_ownership(client, settings, tmp_path):
    item = record(client)
    service = client.app.state.service
    key = Fernet.generate_key().decode()
    path = backup(service.store, tmp_path / "backups", key)
    assert "需要验证".encode() not in path.read_bytes()
    restored = restore(path, tmp_path / "restored", key)
    assert restored.get(item["id"])["body"] == item["body"]
    with pytest.raises(ValueError):
        restore(path, tmp_path / "restored", key)
    root = settings.data_dir / "knowledge"
    root.mkdir(exist_ok=True)
    (root / "user-file").write_text("keep")
    with pytest.raises(ValueError):
        export(service.store, purge=True)
    assert (root / "user-file").read_text() == "keep"


def test_mem0_wire_contract(settings):
    calls = []
    def handler(req):
        calls.append(req)
        if req.method == "DELETE": return httpx.Response(200, json={"message": "deleted"})
        body = json.loads(req.content)
        if "search" in req.url.path:
            return httpx.Response(200, json={"results": [{"memory": "untrusted", "metadata": {"record_id": "r1"}}]})
        assert body["infer"] is False and body["app_id"] == "duo"
        return httpx.Response(200, json={"status": "SUCCEEDED", "results": []})
    mem = Mem0(settings, httpx.MockTransport(handler))
    mem.index(dict(id="r1", title="t", body="b", data={}, author="alice", project="p", revision=1))
    assert mem.search("test") == ["r1"]
    assert calls[0].url.params["user_id"] == "duo:r1"


def test_feishu_card_plain_text_and_dedup_uuid(settings):
    calls = []
    def handler(req):
        calls.append(req)
        if "tenant_access_token" in req.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token", "expire": 7200})
        body = json.loads(req.content)
        content = json.loads(body["content"])
        assert content["elements"][0]["text"]["tag"] == "plain_text"
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "sent"}})
    f = Feishu(settings, httpx.MockTransport(handler))
    item = dict(id="r1", revision=2, title="@所有人", body="<at id=all>untrusted</at>")
    f.send(item, card=True)
    f.send(item, card=True)
    assert json.loads(calls[-1].content)["uuid"] == json.loads(calls[-2].content)["uuid"]


def test_concurrent_events_and_unique_ids(settings):
    service = Collaboration(settings)
    ids = []
    def create():
        ids.append(service.create(settings.members[0], dict(kind="share", title="x", body="x"))["id"])
    threads = [threading.Thread(target=create) for _ in range(12)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(set(ids)) == 12


def test_legacy_cli_reads_only_confirmed_decisions(client, settings):
    source = record(client)
    decision = record(client, kind="decision", parents=[source["id"]])
    root = export(client.app.state.service.store)
    assert MemoryStore.open(root).list_entries("decision") == []
    for user in ("ou_alice", "ou_bob"):
        callback(client, settings, vote(settings, decision["id"], user))
    export(client.app.state.service.store)
    assert MemoryStore.open(root).list_entries("decision")[0].status.value == "active"


def test_recall_before_delivery_never_archives(client, settings):
    body = {"header": {"app_id": settings.app_id, "token": settings.verification_token,
                       "event_type": "im.message.recalled_v1"}, "event": {"message_id": "om_1"}}
    assert callback(client, settings, body).status_code == 200
    assert callback(client, settings, message(settings, "late-private-original")).json()["ignored"]
    assert client.get("/api/search?q=late-private", headers=auth()).json()["results"] == []


def test_unparsed_resources_and_thread_provenance(client, settings):
    body = message(settings)
    body["event"]["message"].update(message_type="audio", root_id="thread-1", content=json.dumps({"file_key": "resource-key"}))
    response = callback(client, settings, body)
    item = client.get(f'/api/records/{response.json()["id"]}', headers=auth()).json()
    assert item["data"]["parse_status"] == "unparsed"
    assert item["data"]["thread_id"] == "thread-1"


def test_experiment_revision_preserves_data_and_checks_result(client):
    item = record(client, kind="experiment", data={"owner": "alice", "expected_observation": "paid pilot", "review_date": "2026-11-01"})
    payload = {"revision": 1, "title": "修订实验", "body": "访谈结果"}
    response = client.put(f'/api/records/{item["id"]}', json=payload, headers=auth())
    assert response.json()["data"]["owner"] == "alice"
    payload.update(revision=2, data={**item["data"], "outcome": "magically-proven"})
    assert client.put(f'/api/records/{item["id"]}', json=payload, headers=auth()).status_code == 409


def test_latest_focus_is_one_per_person(client):
    record(client, kind="focus", title="alice old focus")
    record(client, kind="focus", title="alice new focus")
    response = client.post("/api/records", json={"kind": "focus", "title": "bob focus", "body": "b"}, headers=auth("bob"))
    assert response.status_code == 201
    focus = client.get("/api/briefing", headers=auth()).json()["focus"]
    assert {r["author"] for r in focus} == {"alice", "bob"}
    assert next(r for r in focus if r["author"] == "alice")["title"] == "alice new focus"


def test_digest_quiet_and_once_per_day(settings, monkeypatch):
    service = Collaboration(replace(settings, digest_enabled=True, digest_hour=0))
    worker = Worker(service)
    assert service.digest() is None
    worker.schedule_digest()
    assert service.store.all() == []
    service.create(settings.members[0], dict(kind="share", title="new thought", body="why"))
    worker.schedule_digest()
    worker.schedule_digest()
    assert len([r for r in service.store.all() if r["kind"] == "digest"]) == 1
    assert len([j for j in service.store.jobs() if j["kind"] == "send"]) == 1


def test_disabled_mem0_cannot_claim_remote_erasure(settings):
    service = Collaboration(settings)
    item = service.create(settings.members[0], dict(kind="share", title="t", body="b"))
    class Provider:
        def index(self, r): pass
    worker = Worker(service, semantic=Provider())
    worker.tick()
    service.store.withdraw(item["id"], "alice")
    worker.semantic = None
    for _ in range(10):
        if not worker.tick(): break
    deletion = next(j for j in service.store.jobs() if j["kind"] == "delete_index")
    assert deletion["state"] == "pending" and deletion["attempts"] == 1


def test_withdrawal_rotates_managed_backups(client, settings, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("COLLAB_BACKUP_KEY", key)
    item = record(client, body="old-backup-sensitive")
    service = client.app.state.service
    old = backup(service.store, settings.data_dir / "backups", key)
    service.store.withdraw(item["id"], "alice")
    worker = Worker(service)
    worker.tick()
    assert not old.exists()
    latest = list((settings.data_dir / "backups").glob("*.fernet"))
    assert len(latest) == 1
    restored = restore(latest[0], settings.data_dir / "restored", key)
    assert restored.get(item["id"])["body"] == ""


def test_mcp_has_no_publish_or_confirm_tool(tmp_path, monkeypatch):
    import asyncio
    from team_share.collaboration import mcp as bridge
    monkeypatch.setenv("COLLAB_OUTBOX", str(tmp_path / "outbox"))
    tools = asyncio.run(bridge.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {"search_team", "get_team_record", "prepare_team_review", "stage_team_share", "stage_team_record"}
    got = bridge.stage_team_record("topic", "private topic", "not yet public")
    assert got["uploaded"] is False and Path(got["local_candidate"]).exists()


def test_init_credentials_and_no_path_traversal(tmp_path):
    from team_share.collaboration.__main__ import init
    bad = tmp_path / "bad"
    with pytest.raises(ValueError):
        init(bad, ["../escape", "bob"])
    assert not bad.exists()
    root = tmp_path / "server-config"
    init(root, ["alice", "bob"])
    settings = Settings.load(root / "config.json")
    assert settings.chat_id == "" and settings.mem0_enabled is False
    publisher = json.loads((root / "alice-publisher.json").read_text())["token"]
    reader = json.loads((root / "alice-reader.json").read_text())["token"]
    assert settings.identify(publisher)[1] == "publisher"
    assert settings.identify(reader)[1] == "reader"
    assert publisher not in (root / "config.json").read_text()
    assert (root / "secrets.env").stat().st_mode & 0o777 == 0o600


def test_query_response_retracts_with_source(client, settings):
    source = record(client, title="unique-search-term")
    body = message(settings, "/find unique-search-term")
    callback(client, settings, body)
    class FakeFeishu:
        def __init__(self): self.sent, self.deleted = [], []
        def send(self, r, card=False):
            self.sent.append(r)
            return "sent-" + r["id"]
        def delete(self, mid): self.deleted.append(mid)
    provider = FakeFeishu()
    service = client.app.state.service
    worker = Worker(service, feishu=provider)
    for _ in range(30):
        if not worker.tick(): break
    assert len(provider.sent) == 1
    response_id = provider.sent[0]["id"]
    assert source["id"] in service.store.parents(response_id)
    service.store.withdraw(source["id"], "alice")
    for _ in range(30):
        if not worker.tick(): break
    assert service.store.get(response_id)["status"] == "withdrawn"
    assert provider.deleted == ["sent-" + response_id]


def test_consensus_provenance_after_supersession(client, settings):
    source = record(client)
    old = record(client, kind="decision", parents=[source["id"]])
    for user in ("ou_alice", "ou_bob"):
        callback(client, settings, vote(settings, old["id"], user))
    new = record(client, kind="decision", parents=[source["id"]], data={"replaces": old["id"]})
    for user in ("ou_alice", "ou_bob"):
        callback(client, settings, vote(settings, new["id"], user))
    detail = client.get(f'/api/records/{old["id"]}', headers=auth()).json()
    assert set(detail["confirmed_by"]) == {"alice", "bob"}


def test_same_thread_and_topic_backlinks_are_retrievable(client, settings):
    root = callback(client, settings, message(settings)).json()["id"]
    reply_body = message(settings, "跟进这个问题", mid="om_reply")
    reply_body["event"]["message"]["root_id"] = "om_1"
    reply = callback(client, settings, reply_body).json()["id"]
    topic = record(client, kind="topic", parents=[root, reply])
    source = client.get(f'/api/records/{root}', headers=auth()).json()
    assert set(source["thread_records"]) == {root, reply}
    assert source["referenced_by"] == [topic["id"]]


def test_both_members_discuss_same_topic_without_overwriting_views(client):
    topic = record(client, kind="topic", title="shared product question")
    payload = {"title": "bob's different view", "body": "different reasons", "topic_id": topic["id"]}
    response = client.post("/api/records", json=payload, headers=auth("bob"))
    assert response.status_code == 201
    discussion = client.get(f'/api/topics/{topic["id"]}', headers=auth(role="read")).json()
    assert discussion["discussion"][0]["author"] == "bob"
    client.delete(f'/api/records/{topic["id"]}', headers=auth())
    # Association alone must not erase an independently authored viewpoint.
    assert client.get(f'/api/records/{response.json()["id"]}', headers=auth()).json()["status"] == "active"


def test_real_http_client_bypasses_ambient_proxy_and_keeps_prefix(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from team_share.collaboration.client import request
    paths = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "socks5://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    try:
        got = request(f'http://127.0.0.1:{server.server_port}/team-collab', "reader", "GET", "/api/briefing")
        assert got == {"ok": True} and paths == ["/team-collab/api/briefing"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_repeated_withdrawal_is_idempotent(client):
    item = record(client)
    path = f'/api/records/{item["id"]}'
    client.delete(path, headers=auth())
    first = client.get(path, headers=auth()).json()
    assert client.delete(path, headers=auth()).json()["withdrawn"] == []
    assert client.get(path, headers=auth()).json()["revision"] == first["revision"]


def test_backup_process_lock_is_shared_across_processes(settings):
    import subprocess
    import sys
    service = Collaboration(settings)
    script = '''
from pathlib import Path
import sys
from team_share.collaboration.store import ProcessLock
lock=ProcessLock(Path(sys.argv[1]))
print('ready',flush=True)
with lock:
    print('acquired',flush=True)
'''
    with service.store.lock:
        child = subprocess.Popen([sys.executable, "-c", script, str(settings.data_dir / "gateway.lock")],
                                 stdout=subprocess.PIPE, text=True)
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(subprocess.TimeoutExpired):
            child.communicate(timeout=0.1)
    stdout, _ = child.communicate(timeout=5)
    assert "acquired" in stdout and child.returncode == 0


def test_search_excludes_query_commands_derived_and_unparsed_records(client, settings):
    source = record(client, title="needle-primary", body="original knowledge")
    query = callback(client, settings, message(settings, "/查 needle-primary", mid="query-only")).json()["id"]
    unparsed = record(client, title="needle-primary raw attachment", data={"parse_status": "unparsed"})
    service = client.app.state.service
    derived = []
    with service.store.transaction() as db:
        for kind in ("response", "digest"):
            derived.append(service.store.create(db, kind=kind, author="alice", title="needle-primary generated", body="derived output")["id"])
    class StaleIndex:
        def search(self, q): return [query, unparsed["id"], *derived, source["id"]]
    for provider in (None, StaleIndex()):
        result = service.search("needle-primary", semantic=provider)
        assert [r["id"] for r in result["results"]] == [source["id"]]
    # Stored records remain available by ID for provenance and troubleshooting.
    assert service.detail(query)["body"] == "/查 needle-primary"


def test_repeated_feishu_queries_cite_original_source_without_reply_feedback(client, settings):
    source = record(client, title="needle-repeat", body="original source")
    class FakeFeishu:
        def __init__(self): self.sent = []
        def send(self, item, card=False):
            self.sent.append(item)
            return "sent-" + item["id"]
        def delete(self, mid): pass
    provider = FakeFeishu()
    service = client.app.state.service
    worker = Worker(service, feishu=provider)
    for index in range(2):
        command = callback(client, settings, message(settings, "/查 needle-repeat", mid=f"repeat-{index}")).json()["id"]
        for _ in range(30):
            if not worker.tick(): break
        response = provider.sent[-1]
        assert set(service.store.parents(response["id"])) == {source["id"], command}
        assert "/查" not in response["body"]
    assert len(provider.sent) == 2
    assert [r["id"] for r in service.search("needle-repeat")["results"]] == [source["id"]]


def test_archive_feed_reader_pagination_withdrawal_and_commands(client):
    service = client.app.state.service
    alice = service.settings.members[0]
    def add(text):
        return service.create(alice, dict(kind="share", title=text, body=text), source="feishu")
    a = add("归档来源 alpha")
    add("/查 alpha")
    b = add("归档来源 beta")
    record(client, body="本机来源不自动收集")
    assert client.get("/api/archive-feed").status_code == 401
    first = client.get("/api/archive-feed?limit=1", headers=auth(role="read")).json()
    assert [r["id"] for r in first["records"]] == [a["id"]]
    second = client.get("/api/archive-feed", params={"cursor": first["next_cursor"], "limit": 1}, headers=auth(role="read")).json()
    assert second["records"] == [] and second["next_cursor"] != first["next_cursor"]
    third = client.get("/api/archive-feed", params={"cursor": second["next_cursor"]}, headers=auth(role="read")).json()
    assert [r["id"] for r in third["records"]] == [b["id"]]
    service.store.withdraw(a["id"], "alice")
    changed = client.get("/api/archive-feed", params={"cursor": third["next_cursor"]}, headers=auth(role="read")).json()
    assert changed["records"][0]["id"] == a["id"]
    assert changed["records"][0]["status"] == "withdrawn"
    assert not changed["records"][0]["body"]
    assert client.get("/api/archive-feed?cursor=bad", headers=auth(role="read")).status_code == 409
