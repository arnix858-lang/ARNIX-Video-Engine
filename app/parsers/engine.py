from __future__ import annotations

from typing import Any

import anime_dl_core as adc
from anime_dl_core.sources import Alloha


class ParserError(Exception):
    pass


def resolve_embed(url: str) -> dict[str, Any]:
    """Resolve supported public player embeds through anime-dl-core."""
    try:
        result = adc.extract(url)
    except Exception as exc:
        raise ParserError(f"Could not resolve this player: {exc}") from exc

    streams = []
    for stream in result.streams:
        streams.append({
            "url": stream.url,
            "kind": str(getattr(stream.kind, "value", stream.kind)).lower(),
            "quality": stream.quality,
            "label": stream.label,
            "headers": dict(stream.headers or {}),
            "is_master": bool(getattr(stream, "is_master", False)),
        })
    return {
        "provider": result.player,
        "title": result.title,
        "poster": result.poster,
        "translation": result.translation,
        "qualities": result.qualities,
        "streams": streams,
        "skip_segments": [
            {"start": s.start, "end": s.end, "kind": s.kind}
            for s in (result.skip_segments or [])
        ],
    }


def search_alloha(query: str, token: str | None = None, season: int = 1, episode: int = 1, translation: str | None = None) -> list[dict[str, Any]]:
    """Search Alloha and build an iframe using a dub available for this episode."""
    kwargs = {"token": token} if token else {}
    try:
        with Alloha(**kwargs) as source:
            item = source.find(name=query)
            if item is None:
                return []
            items = item if isinstance(item, (list, tuple)) else [item]
            output = []
            for anime in items:
                # Alloha dubs can differ by episode; anime.translations is only
                # a title-level list and may contain unavailable choices.
                voices = source.translations_for(anime, season=season, episode=episode)
                voice_names = [getattr(v, "name", str(v)) for v in voices]
                selected = None
                if translation:
                    selected = next(
                        (v for v in voices if getattr(v, "name", str(v)).casefold() == translation.casefold()),
                        None,
                    )
                if selected is None and voices:
                    selected = voices[0]
                if not selected:
                    raise ParserError(
                        f"No Alloha translations available for season {season}, episode {episode}"
                    )
                selected_name = getattr(selected, "name", str(selected))
                output.append({
                    "name": getattr(anime, "name", None),
                    "year": getattr(anime, "year", None),
                    "category": getattr(anime, "category", None),
                    "seasons": getattr(anime, "seasons", {}),
                    "translations": voice_names,
                    "selected_translation": selected_name,
                    "iframe": source.iframe(
                        anime, season=season, episode=episode,
                        translation=selected_name,
                    ),
                    "note": "Alloha provides an iframe; direct HLS extraction is not exposed by the library.",
                })
            return output
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError(f"Alloha search failed: {exc}") from exc



def resolve_iframe(iframe_url: str) -> dict[str, Any]:
    """Extract publicly available direct formats from a supported iframe/player URL.

    This uses yt-dlp's site extractors. It does not bypass DRM, login,
    subscription, or geographic restrictions.
    """
    try:
        import yt_dlp

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 20,
            "retries": 1,
            "extractor_retries": 1,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(iframe_url, download=False)

        if not info:
            raise ParserError("The iframe extractor returned no video information")

        entries = info.get("entries") or [info]
        formats: list[dict[str, Any]] = []
        for entry in entries:
            if not entry:
                continue
            for item in entry.get("formats") or []:
                stream_url = item.get("url")
                if not stream_url:
                    continue
                protocol = str(item.get("protocol") or "").lower()
                if not (stream_url.startswith("https://") or stream_url.startswith("http://")):
                    continue
                formats.append({
                    "format_id": item.get("format_id"),
                    "quality": item.get("format_note") or item.get("resolution"),
                    "height": item.get("height"),
                    "width": item.get("width"),
                    "tbr": item.get("tbr"),
                    "ext": item.get("ext"),
                    "protocol": protocol,
                    "url": stream_url,
                    "headers": item.get("http_headers") or entry.get("http_headers") or {},
                })

        # Some extractors expose only a single top-level media URL.
        if not formats and info.get("url"):
            formats.append({
                "format_id": info.get("format_id"),
                "quality": info.get("format_note") or info.get("resolution"),
                "height": info.get("height"),
                "width": info.get("width"),
                "ext": info.get("ext"),
                "protocol": info.get("protocol"),
                "url": info["url"],
                "headers": info.get("http_headers") or {},
            })

        if not formats:
            raise ParserError(
                "No direct formats were exposed by this iframe. The player may be unsupported or require browser JavaScript."
            )

        # Prefer HLS/DASH and higher resolutions, but retain all available formats.
        formats.sort(
            key=lambda x: (
                1 if "m3u8" in str(x.get("protocol", "")).lower() or "dash" in str(x.get("protocol", "")).lower() else 0,
                x.get("height") or 0,
                x.get("tbr") or 0,
            ),
            reverse=True,
        )
        return {
            "title": info.get("title"),
            "extractor": info.get("extractor_key") or info.get("extractor"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "formats": formats,
            "note": "Only formats exposed by supported yt-dlp extractors are returned; DRM and access restrictions are not bypassed.",
        }
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError(f"Could not extract streams from iframe: {exc}") from exc
