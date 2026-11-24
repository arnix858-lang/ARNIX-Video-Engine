import time

import pytest
from fastapi import HTTPException

from app.security import sign_payload, validate_http_url, validate_public_host, verify_payload


def test_signed_payload_round_trip():
    token = sign_payload({"url": "https://cdn.example/video.m3u8"}, "test-secret")
    assert verify_payload(token, "test-secret")["url"] == "https://cdn.example/video.m3u8"


def test_tampered_token_rejected():
    token = sign_payload({"url": "https://cdn.example/video.m3u8"}, "test-secret")
    with pytest.raises(HTTPException):
        verify_payload(token + "x", "test-secret")


def test_expired_token_rejected():
    token = sign_payload({"url": "https://cdn.example/video.m3u8", "exp": int(time.time()) - 10}, "test-secret")
    with pytest.raises(HTTPException):
        verify_payload(token, "test-secret")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com/a"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(HTTPException):
        validate_http_url(url)


def test_https_url_allowed():
    assert validate_http_url("https://cdn.example/a.m3u8") == "https://cdn.example/a.m3u8"


@pytest.mark.parametrize("url", ["http://127.0.0.1/video", "http://localhost/video", "http://192.168.1.10/video"])
def test_private_hosts_rejected(url):
    with pytest.raises(HTTPException):
        validate_public_host(url)
