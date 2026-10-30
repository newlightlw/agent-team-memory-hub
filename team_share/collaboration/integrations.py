from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class Feishu:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport
        self._token = ""
        self._expires = 0

    def verify(self, raw: bytes, headers):
        s = self.settings
        if not s.encrypt_key or not s.verification_token:
            raise PermissionError("Feishu callback credentials not configured")
        body = json.loads(raw)
        if "encrypt" in body:
            enc = base64.b64decode(body["encrypt"], validate=True)
            decryptor = Cipher(algorithms.AES(hashlib.sha256(s.encrypt_key.encode()).digest()),
                               modes.CBC(enc[:16])).decryptor()
            padded = decryptor.update(enc[16:]) + decryptor.finalize()
            unpad = padding.PKCS7(128).unpadder()
            body = json.loads(unpad.update(padded) + unpad.finalize())
        token = body.get("header", {}).get("token", body.get("token"))
        # URL validation can arrive without signature headers. Its verification
        # token is still required and it cannot mutate records.
        if body.get("type") == "url_verification":
            if not isinstance(token, str) or not hmac.compare_digest(token, s.verification_token):
                raise PermissionError("invalid challenge token")
            return body
        stamp = headers.get("x-lark-request-timestamp", "")
        nonce = headers.get("x-lark-request-nonce", "")
        signature = headers.get("x-lark-signature", "")
        if not stamp.isdigit() or abs(time.time() - int(stamp)) > 300 or not nonce:
            raise PermissionError("expired callback")
        digest = hashlib.sha256((stamp + nonce + s.encrypt_key).encode() + raw).hexdigest()
        if not hmac.compare_digest(signature, digest):
            raise PermissionError("invalid callback signature")
        if token is not None and not hmac.compare_digest(str(token), s.verification_token):
            raise PermissionError("invalid callback token")
        if body.get("header", {}).get("app_id") != s.app_id:
            raise PermissionError("wrong Feishu application")
        return body

    def call(self, method, path, payload=None, *, authorize=True):
        if authorize and time.time() >= self._expires:
            result = self.call("POST", "/auth/v3/tenant_access_token/internal", {
                "app_id": self.settings.app_id, "app_secret": self.settings.app_secret,
            }, authorize=False)
            self._token = result["tenant_access_token"]
            self._expires = time.time() + result.get("expire", 7200) - 60
        with httpx.Client(base_url="https://open.feishu.cn/open-apis", timeout=10, trust_env=False,
                          transport=self.transport) as client:
            response = client.request(method, path, json=payload,
                                      headers={"Authorization": f"Bearer {self._token}"} if authorize else {})
        response.raise_for_status()
        result = response.json()
        if result.get("code", 0) != 0:
            # Do not log provider responses: they may echo private content.
            raise RuntimeError("Feishu API rejected request")
        return result

    def send(self, record, card=False):
        if not self.settings.chat_id or not self.settings.app_secret:
            raise RuntimeError("Feishu sending not configured")
        if card:
            content = {
                "header": {"title": {"tag": "plain_text", "content": record["title"][:100]}},
                "elements": [
                    {"tag": "div", "text": {"tag": "plain_text", "content": record["body"][:3000]}},
                    {"tag": "div", "text": {"tag": "plain_text", "content":
                        f'{record["id"]} · v{record["revision"]} · 确认表示同意本版本，非实验验证成功'}},
                    {"tag": "action", "actions": [{"tag": "button", "type": "primary",
                        "text": {"tag": "plain_text", "content": "确认此版本"},
                        "value": {"action": "confirm", "id": record["id"], "revision": record["revision"]}}]},
                ],
            }
        else:
            content = {"text": record["body"][:10000]}
        result = self.call("POST", "/im/v1/messages?receive_id_type=chat_id", {
            "receive_id": self.settings.chat_id, "msg_type": "interactive" if card else "text",
            "content": json.dumps(content, ensure_ascii=False),
            "uuid": uuid.uuid5(uuid.NAMESPACE_URL, record["id"] + str(record["revision"])).hex,
        })
        return result["data"]["message_id"]

    def delete(self, message_id):
        self.call("DELETE", f"/im/v1/messages/{message_id}")


class Mem0:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def call(self, method, path, **kwargs):
        with httpx.Client(base_url="https://api.mem0.ai", timeout=10, trust_env=False, transport=self.transport,
                          headers={"Authorization": f"Token {self.settings.mem0_key}", "Accept": "application/json"}) as client:
            result = client.request(method, path, **kwargs)
            result.raise_for_status()
            return result.json()

    def search(self, query):
        result = self.call("POST", "/v3/memories/search/", json={
            "query": query, "filters": {"app_id": self.settings.team_id}, "top_k": 30,
        })
        return [r.get("metadata", {}).get("record_id") for r in result.get("results", [])]

    def delete(self, rid):
        result = self.call("DELETE", "/v1/memories/", params={"user_id": f"{self.settings.team_id}:{rid}"})
        if result.get("event_id"):
            # Bounded polling; failures remain in durable outbox for retry.
            for _ in range(5):
                event = self.call("GET", f'/v1/event/{result["event_id"]}/')
                state = event.get("status", event.get("event", {}).get("status"))
                if state == "SUCCEEDED":
                    return
                if state == "FAILED":
                    raise RuntimeError("Mem0 deletion failed")
                time.sleep(0.2)
            raise RuntimeError("Mem0 deletion not yet confirmed")

    def index(self, record):
        self.delete(record["id"])
        result = self.call("POST", "/v3/memories/add/", json={
            "user_id": f'{self.settings.team_id}:{record["id"]}',
            "app_id": self.settings.team_id, "infer": False, "immutable": True,
            "messages": [{"role": "user", "content": json.dumps({
                "title": record["title"], "body": record["body"], "data": record["data"],
            }, ensure_ascii=False)}],
            "metadata": {"record_id": record["id"], "author": record["author"],
                         "project": record["project"], "revision": record["revision"]},
        })
        if result.get("status") in ("FAILED", "PENDING"):
            raise RuntimeError("Mem0 direct import not confirmed")
