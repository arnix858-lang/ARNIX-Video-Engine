from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import urlparse

from fastapi import HTTPException


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_payload(payload: dict, secret: str) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = _b64(raw)
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_payload(token: str, secret: str) -> dict:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        value = json.loads(_unb64(body))
        if not isinstance(value, dict):
            raise ValueError("bad payload")
        return value
    except Exception as exc:
        raise HTTPException(status_code=403, detail="Invalid or expired stream token") from exc


def validate_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only absolute HTTP(S) stream URLs are supported")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in stream URLs are not allowed")
    return url
