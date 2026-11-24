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


def search_alloha(query: str, token: str | None = None) -> list[dict[str, Any]]:
    """Search Alloha catalog and return its supported iframe fallback.

    Alloha's current player link is an iframe. The library documentation does
    not claim direct HLS extraction from Alloha, so this function never invents
    a direct video URL.
    """
    kwargs = {"token": token} if token else {}
    try:
        with Alloha(**kwargs) as source:
            item = source.find(name=query)
            if item is None:
                return []
            # find() may return one object or a sequence depending on source version.
            items = item if isinstance(item, (list, tuple)) else [item]
            output = []
            for anime in items:
                translations = [t.name for t in getattr(anime, "translations", [])]
                output.append({
                    "name": getattr(anime, "name", None),
                    "year": getattr(anime, "year", None),
                    "category": getattr(anime, "category", None),
                    "seasons": getattr(anime, "seasons", {}),
                    "translations": translations,
                    "note": "Alloha provides an iframe; direct HLS extraction is not exposed by the library.",
                })
            return output
    except Exception as exc:
        raise ParserError(f"Alloha search failed: {exc}") from exc
