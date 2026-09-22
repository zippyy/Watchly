import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.services.nuvio import nuvio_service
from app.services.redis_service import redis_service
from app.services.simkl import simkl_service
from app.services.token_store import token_store

ENABLED_KEY = "watchly:nuvio_simkl_sync:enabled"
RESULT_PREFIX = "watchly:nuvio_simkl_sync:last:"
SYNC_INTERVAL_SECONDS = 15 * 60


@dataclass
class SyncResult:
    added: int = 0
    skipped: int = 0
    watched: int = 0
    unmatched: int = 0
    failed: int = 0
    candidates: int = 0
    library: int = 0
    synced_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _imdb_id(row: dict[str, Any]) -> str | None:
    for key in ("content_id", "imdb_id", "imdb"):
        value = str(row.get(key) or "").strip()
        if value.startswith("tt"):
            return value
    ids = row.get("ids")
    if isinstance(ids, dict):
        value = str(ids.get("imdb") or "").strip()
        if value.startswith("tt"):
            return value
    return None


def _media_type(row: dict[str, Any]) -> str | None:
    value = str(row.get("content_type") or row.get("type") or "").lower()
    if value == "movie":
        return "movie"
    if value in {"series", "show", "tv"}:
        return "series"
    return None


async def sync_nuvio_library_to_simkl(token: str) -> SyncResult:
    token = await token_store.resolve_alias(token)
    credentials = await token_store.get_user_data(token)
    if not credentials:
        raise ValueError("Watchly token not found")

    user_settings = credentials.get("settings") or {}
    nuvio_token = user_settings.get("nuvio_access_token")
    simkl_token = user_settings.get("simkl_access_token")
    profile_id = user_settings.get("nuvio_profile_id")
    if not nuvio_token or profile_id is None:
        raise ValueError("Nuvio Sync is not connected")
    if not simkl_token:
        raise ValueError("Simkl is not connected")
    if not settings.SIMKL_CLIENT_ID:
        raise ValueError("Simkl is not configured on this Watchly server")

    logger.info(f"[{redact_token(token)}] [simkl-sync] Starting Nuvio -> Simkl sync")
    library, watched_rows, simkl_history = await asyncio.gather(
        nuvio_service.get_library_items(nuvio_token, int(profile_id)),
        nuvio_service.get_watched_items(nuvio_token, int(profile_id)),
        simkl_service.get_history(simkl_token, settings.SIMKL_CLIENT_ID),
    )

    watched_ids = {_imdb_id(row) for row in watched_rows}
    watched_ids.discard(None)
    simkl_ids = {item.imdb_id for item in simkl_history.items if item.imdb_id}

    result = SyncResult(library=len(library))
    movies: list[str] = []
    shows: list[str] = []
    seen: set[str] = set()

    for row in library:
        imdb_id = _imdb_id(row)
        media_type = _media_type(row)
        if not imdb_id or not media_type:
            result.unmatched += 1
            continue
        if imdb_id in seen:
            result.skipped += 1
            continue
        seen.add(imdb_id)
        if imdb_id in watched_ids:
            result.watched += 1
            continue
        if imdb_id in simkl_ids:
            result.skipped += 1
            continue
        result.candidates += 1
        (movies if media_type == "movie" else shows).append(imdb_id)

    # Simkl supports bulk sync writes; chunk to keep request bodies bounded.
    for start in range(0, max(len(movies), len(shows)), 100):
        movie_chunk = movies[start : start + 100]
        show_chunk = shows[start : start + 100]
        if not movie_chunk and not show_chunk:
            continue
        response = await simkl_service.add_to_plan_to_watch(
            simkl_token,
            settings.SIMKL_CLIENT_ID,
            movies=movie_chunk,
            shows=show_chunk,
        )
        not_found = response.get("not_found") or {}
        failed_movies = len(not_found.get("movies") or [])
        failed_shows = len(not_found.get("shows") or [])
        chunk_failed = failed_movies + failed_shows
        result.failed += chunk_failed
        result.added += len(movie_chunk) + len(show_chunk) - chunk_failed

    result.synced_at = datetime.now(timezone.utc).isoformat()
    await redis_service.set(RESULT_PREFIX + token, __import__("json").dumps(result.to_dict()))
    logger.info(
        f"[{redact_token(token)}] [simkl-sync] complete library={result.library} "
        f"candidates={result.candidates} added={result.added} skipped={result.skipped} "
        f"watched={result.watched} unmatched={result.unmatched} failed={result.failed}"
    )
    return result


async def set_enabled(token: str, enabled: bool) -> None:
    token = await token_store.resolve_alias(token)
    client = await redis_service.get_client()
    if enabled:
        await client.sadd(ENABLED_KEY, token)
    else:
        await client.srem(ENABLED_KEY, token)


async def is_enabled(token: str) -> bool:
    token = await token_store.resolve_alias(token)
    client = await redis_service.get_client()
    return bool(await client.sismember(ENABLED_KEY, token))


async def last_result(token: str) -> dict[str, Any] | None:
    token = await token_store.resolve_alias(token)
    raw = await redis_service.get(RESULT_PREFIX + token)
    if not raw:
        return None
    try:
        return __import__("json").loads(raw)
    except Exception:
        return None


async def sync_worker() -> None:
    while True:
        try:
            client = await redis_service.get_client()
            tokens = await client.smembers(ENABLED_KEY)
            for raw_token in tokens:
                token = raw_token.decode() if isinstance(raw_token, bytes) else str(raw_token)
                try:
                    await sync_nuvio_library_to_simkl(token)
                except Exception as exc:
                    logger.warning(f"[{redact_token(token)}] [simkl-sync] automatic sync failed: {exc}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"[simkl-sync] worker pass failed: {exc}")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
