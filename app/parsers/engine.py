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
