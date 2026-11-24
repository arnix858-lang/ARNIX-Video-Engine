from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

from fastapi import HTTPException


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_payload(payload: dict, secret: str) -> str:
    data = dict(payload)
    data.setdefault("exp", int(time.time()) + 3600)
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
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
        if int(value.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        return value
    except Exception as exc:
        raise HTTPException(status_code=403, detail="Invalid or expired stream token") from exc


def validate_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Only absolute HTTP(S) stream URLs are supported")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Credentials in stream URLs are not allowed")
    if parsed.port and not 1 <= parsed.port <= 65535:
        raise HTTPException(status_code=400, detail="Invalid URL port")
    return url


def validate_public_host(url: str) -> str:
    """Reject local/private destinations to reduce SSRF risk."""
    safe_url = validate_http_url(url)
    host = urlparse(safe_url).hostname
    assert host is not None
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            addresses = {ipaddress.ip_address(record[4][0]) for record in records}
        except socket.gaierror as exc:
            raise HTTPException(status_code=502, detail="Could not resolve upstream host") from exc
    if not addresses or any(
        not address.is_global or address.is_private or address.is_loopback
        or address.is_link_local or address.is_multicast or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise HTTPException(status_code=403, detail="Private or local upstream addresses are blocked")
    return safe_url
