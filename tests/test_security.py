import pytest
from fastapi import HTTPException

from app.security import sign_payload, validate_http_url, verify_payload


def test_signed_payload_round_trip():
    token = sign_payload({"url": "https://cdn.example/video.m3u8"}, "test-secret")
    assert verify_payload(token, "test-secret")["url"] == "https://cdn.example/video.m3u8"


def test_tampered_token_rejected():
    token = sign_payload({"url": "https://cdn.example/video.m3u8"}, "test-secret")
    with pytest.raises(HTTPException):
        verify_payload(token + "x", "test-secret")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com/a"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(HTTPException):
        validate_http_url(url)


def test_https_url_allowed():
    assert validate_http_url("https://cdn.example/a.m3u8") == "https://cdn.example/a.m3u8"
