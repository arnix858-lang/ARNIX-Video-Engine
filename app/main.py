from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.parsers.engine import ParserError, resolve_embed, search_alloha
from app.security import sign_payload, validate_http_url, verify_payload


class Settings(BaseSettings):
    app_secret: str = "development-only-change-me"
    alloha_token: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
app = FastAPI(
    title="ARNIX Video Engine",
    version="0.1.0",
    description="Independent video source resolver and signed HLS gateway.",
)


class ResolveRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


def _proxy_token(url: str, headers: dict[str, str] | None = None) -> str:
    return sign_payload({"url": validate_http_url(url), "headers": headers or {}}, settings.app_secret)


def _proxy_url(url: str, headers: dict[str, str] | None = None) -> str:
    return "/api/v1/gateway/" + _proxy_token(url, headers)


def _rewrite_playlist(text: str, base_url: str, headers: dict[str, str]) -> str:
    output = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            output.append(line)
        elif stripped.startswith("#"):
            # Rewrite URI="..." attributes used by keys, maps and media renditions.
            def replace_uri(match: re.Match) -> str:
                absolute = urljoin(base_url, match.group(1))
                return 'URI="' + _proxy_url(absolute, headers) + '"'
            output.append(re.sub(r'URI="([^"]+)"', replace_uri, line))
        else:
            output.append(_proxy_url(urljoin(base_url, stripped), headers))
    return "\n".join(output) + "\n"


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
        "note": "Provider availability depends on the embed URL and upstream service status.",
    }


@app.post("/api/v1/resolve")
async def resolve(body: ResolveRequest):
    try:
        data = resolve_embed(body.url)
    except ParserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Only streams returned by the parser are signed for the gateway.
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
async def gateway(token: str):
    payload = verify_payload(token, settings.app_secret)
    url = validate_http_url(str(payload.get("url", "")))
    headers = payload.get("headers") or {}
    if not isinstance(headers, dict):
        raise HTTPException(status_code=400, detail="Invalid stream headers")

    # Avoid forwarding hop-by-hop or host headers from upstream parser output.
    safe_headers = {
        str(k): str(v) for k, v in headers.items()
        if str(k).lower() in {"user-agent", "referer", "origin", "authorization", "cookie"}
    }
    safe_headers.setdefault("User-Agent", "Mozilla/5.0 ARNIX-Video-Engine")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            upstream = await client.get(url, headers=safe_headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}") from exc

    if upstream.status_code >= 400:
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/octet-stream"),
        )

    content_type = upstream.headers.get("content-type", "")
    path = urlparse(str(upstream.url)).path.lower()
    is_playlist = "mpegurl" in content_type.lower() or path.endswith(".m3u8")
    if is_playlist:
        rewritten = _rewrite_playlist(upstream.text, str(upstream.url), safe_headers)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
        )

    return Response(
        content=upstream.content,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


@app.options("/api/v1/{path:path}")
async def cors_preflight(path: str):
    return Response(status_code=204, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
    })


@app.exception_handler(Exception)
async def unhandled_error_handler(request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
