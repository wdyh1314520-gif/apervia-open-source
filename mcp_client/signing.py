"""HMAC signing shared by app3 and the loopback MCP client bridge."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from threading import Lock


def canonical_request(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    digest = hashlib.sha256(body or b"").hexdigest()
    return "\n".join((str(method or "").upper(), str(path or ""), str(timestamp or ""), str(nonce or ""), digest)).encode("utf-8")


def sign_request(secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    return hmac.new(str(secret or "").encode("utf-8"), canonical_request(method, path, timestamp, nonce, body), hashlib.sha256).hexdigest()


def verify_request_signature(secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes, signature: str, *, max_skew_seconds: int = 30) -> tuple[bool, str]:
    if len(str(secret or "")) < 32:
        return False, "bridge_secret_not_configured"
    if not timestamp or not nonce or not signature:
        return False, "signature_headers_missing"
    try:
        request_time = int(timestamp)
    except Exception:
        return False, "signature_timestamp_invalid"
    if abs(time.time() - request_time) > max(1, int(max_skew_seconds)):
        return False, "signature_timestamp_expired"
    expected = sign_request(secret, method, path, timestamp, nonce, body)
    return (True, "") if hmac.compare_digest(expected, str(signature or "")) else (False, "signature_invalid")


@dataclass
class ReplayNonceStore:
    ttl_seconds: int = 120
    max_entries: int = 4096
    _items: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def consume(self, nonce: str) -> bool:
        value = str(nonce or "").strip()
        if not value or len(value) > 160:
            return False
        now = time.time()
        with self._lock:
            for key in [key for key, expires_at in self._items.items() if expires_at <= now]:
                self._items.pop(key, None)
            if value in self._items:
                return False
            if len(self._items) >= max(64, self.max_entries):
                for key, _ in sorted(self._items.items(), key=lambda item: item[1])[: max(1, len(self._items) // 4)]:
                    self._items.pop(key, None)
            self._items[value] = now + max(10, self.ttl_seconds)
        return True
