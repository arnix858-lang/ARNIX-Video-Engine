from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.parsers.engine import ParserError, resolve_embed, search_alloha
from app.security import sign_payload, validate_http_url, validate_public_host, verify_payload


class Settings(BaseSettings):
    app_secret: str = "development-only-change-me"
    alloha_token: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
app = FastAPI(
    title="ARNIX Video Engine",
    version="0.2.0",
    description="Independent video source resolver and signed HLS gateway.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


class ResolveRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


def _proxy_token(url: str, headers: dict[str, str] | None = None) -> str:
    return sign_payload({"url": validate_http_url(url), "headers": headers or {}}, settings.app_secret)


def _proxy_url(url: str, headers: dict[str, str]) -> str:
    return "/api/v1/gateway/" + _proxy_token(url, headers)


def _rewrite_playlist(text: str, base_url: str, headers: dict[str, str]) -> str:
    output = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            output.append(line)
        elif stripped.startswith("#"):
            def replace_uri(match: re.Match) -> str:
                absolute = urljoin(base_url, match.group(1))
                return 'URI="' + _proxy_url(absolute, headers) + '"'
            output.append(re.sub(r'URI="([^"]+)"', replace_uri, line))
        else:
            output.append(_proxy_url(urljoin(base_url, stripped), headers))
    return "\n".join(output) + "\n"


def _safe_headers(headers: object) -> dict[str, str]:
    if not isinstance(headers, dict):
        raise HTTPException(status_code=400, detail="Invalid stream headers")
    safe = {
        str(k): str(v) for k, v in headers.items()
        if str(k).lower() in {"user-agent", "referer", "origin", "authorization", "cookie"}
    }
    safe.setdefault("User-Agent", "Mozilla/5.0 ARNIX-Video-Engine")
    return safe


async def _open_upstream(client: httpx.AsyncClient, url: str, headers: dict[str, str], request_headers: dict[str, str]):
    """Follow redirects manually and validate every destination before connecting."""
    current = validate_public_host(url)
    for _ in range(6):
        outgoing = dict(headers)
        for key in ("range", "if-range"):
            if key in request_headers:
                outgoing[key] = request_headers[key]
        request = client.build_request("GET", current, headers=outgoing)
        response = await client.send(request, stream=True, follow_redirects=False)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        await response.aclose()
        if not location:
            raise HTTPException(status_code=502, detail="Upstream redirect has no location")
        current = validate_public_host(urljoin(current, location))
    raise HTTPException(status_code=502, detail="Too many upstream redirects")


@app.get("/")
async def root():
    return {"name": "ARNIX Video Engine", "version": app.version, "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "arnix-video-engine"}


@app.get("/api/v1/providers")
async def providers():
    return {
        "resolvers": ["kodik", "aniboom", "cvh", "sibnet", "animedia", "anilibria", "vk"],
        "catalog_sources": ["alloha"],
        "planned_adapters": ["hdrezka"],
        "note": "Provider availability depends on the embed URL and upstream service status.",
    }


@app.post("/api/v1/resolve")
async def resolve(body: ResolveRequest):
    try:
        data = resolve_embed(body.url)
    except ParserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for stream in data["streams"]:
        stream["playback_url"] = _proxy_url(stream["url"], stream.get("headers"))
        stream.pop("url", None)
        stream.pop("headers", None)
    return data


@app.get("/api/v1/alloha/search")
async def alloha_search(
    q: str = Query(min_length=2, max_length=200),
    season: int = Query(default=1, ge=1, le=100),
    episode: int = Query(default=1, ge=1, le=1000),
    translation: str | None = Query(default=None, max_length=100),
):
    try:
        return {"results": search_alloha(q, settings.alloha_token, season, episode, translation)}
    except ParserError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/gateway/{token}")
async def gateway_request(token: str, request: Request):
    payload = verify_payload(token, settings.app_secret)
    url = validate_public_host(str(payload.get("url", "")))
    safe_headers = _safe_headers(payload.get("headers") or {})
    client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=12.0))
    try:
        upstream = await _open_upstream(client, url, safe_headers, dict(request.headers))
    except HTTPException:
        await client.aclose()
        raise
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Upstream request failed") from exc

    content_type = upstream.headers.get("content-type", "")
    final_url = str(upstream.url)
    path = urlparse(final_url).path.lower()
    is_playlist = "mpegurl" in content_type.lower() or path.endswith(".m3u8")
    if is_playlist:
        try:
            body = await upstream.aread()
            rewritten = _rewrite_playlist(body.decode("utf-8", errors="replace"), final_url, safe_headers)
        finally:
            await upstream.aclose()
            await client.aclose()
        return Response(
            content=rewritten,
            status_code=upstream.status_code,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )

    response_headers = {}
    for name in ("content-length", "content-range", "accept-ranges", "etag", "last-modified"):
        if name in upstream.headers:
            response_headers[name] = upstream.headers[name]
    response_headers["Cache-Control"] = "no-store"

    async def stream_body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        media_type=content_type or "application/octet-stream",
        headers=response_headers,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
