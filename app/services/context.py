from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings, watch_history_source_key
from app.models.library import LibraryCollection
from app.services.auth import auth_service
from app.services.history_merge import merge_watch_histories
from app.services.stremio.library import stremio_library_to_watch_history, watch_history_to_library_collection
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.user_cache import user_cache


@dataclass
class UserContext:
    """Everything a request handler needs about a user.

    The caller MUST call close() when done (or use as async context manager).
    """

    token: str
    credentials: dict[str, Any]
    user_settings: UserSettings
    auth_key: str | None
    library: LibraryCollection
    bundle: StremioBundle

    async def close(self):
        await self.bundle.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()


def extract_settings(credentials: dict[str, Any]) -> UserSettings:
    """Parse UserSettings from credentials, falling back to defaults."""
    settings_dict = credentials.get("settings", {})
    return UserSettings(**settings_dict) if settings_dict else get_default_settings()


async def load_user_context(
    token: str,
    *,
    require_auth: bool = True,
) -> UserContext:
    """Load credentials, settings, auth key, and library for a token.

    The library is sourced from `user_settings.watch_history_sources`.
    Selected provider histories are merged by IMDb ID before they are converted
    to the shared LibraryCollection shape. If one selected source fails, the
    remaining sources still contribute; if all fail and Stremio credentials are
    available, Watchly falls back to the Stremio library.
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing token. Please reconfigure the addon.",
        )

    # Manifest URLs installed before an account merge carry the absorbed token.
    token = await token_store.resolve_alias(token)
    credentials = await token_store.get_user_data(token)
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Token not found. Please reconfigure the addon.",
        )

    user_settings = extract_settings(credentials)
    bundle = StremioBundle()

    try:
        configured_sources = user_settings.watch_history_sources
        configured_key = watch_history_source_key(configured_sources)

        # Stremio is a hard requirement only when it is the sole selected source.
        # In a merged setup, an expired Stremio session should not throw away valid
        # Trakt/Simkl/Nuvio history; it is skipped and retried on a later request.
        if require_auth and configured_sources == ["stremio"]:
            auth_key = await auth_service.require_auth_key(bundle, credentials, token)
        else:
            auth_key = await auth_service.resolve_auth_key_with_bundle(bundle, credentials, token)

        # Partial-source libraries intentionally carry the key for the providers
        # that actually succeeded. A mismatch makes the next request retry any
        # configured provider that was temporarily unavailable.
        cached = await user_cache.get_library_items(token)
        if cached and getattr(cached, "source", "stremio") != configured_key:
            logger.info(
                f"[{redact_token(token)}] Cached library source "
                f"'{cached.source}' != configured '{configured_key}'; invalidating."
            )
            await user_cache.invalidate_library_items(token)
            cached = None

        library = cached
        if not library:
            library = await fetch_library_for_sources(configured_sources, user_settings, token, bundle, auth_key)
            if library is not None:
                await user_cache.set_library_items(token, library)

        if not library:
            library = LibraryCollection()

        return UserContext(
            token=token,
            credentials=credentials,
            user_settings=user_settings,
            auth_key=auth_key,
            library=library,
            bundle=bundle,
        )
    except Exception:
        await bundle.close()
        raise


async def fetch_library_for_sources(
    sources: list[str],
    user_settings: UserSettings,
    token: str,
    bundle: StremioBundle,
    auth_key: str | None,
) -> LibraryCollection | None:
    """Fetch and merge all selected history sources.

    Provider failures are isolated. A source that returns an empty history still
    counts as successful; only None means the fetch failed. The resulting
    LibraryCollection source key records exactly which configured providers
    contributed so the cache retries partial failures on the next request.
    """
    from app.services.profile.service import ProfileService

    profile_service = ProfileService()
    histories = []
    successful_sources: list[str] = []
    stremio_library: LibraryCollection | None = None

    for source in sources:
        if source == "stremio":
            if not auth_key:
                logger.warning(f"[{redact_token(token)}] Stremio selected but no valid session is available.")
                continue
            try:
                stremio_library = await bundle.library.get_library_items(auth_key)
                histories.append(stremio_library_to_watch_history(stremio_library))
                successful_sources.append("stremio")
            except Exception as exc:
                logger.warning(f"[{redact_token(token)}] Stremio history fetch failed: {exc}")
            continue

        history, _, _ = await profile_service.fetch_external_watch_history(source, user_settings, token)
        if history is None:
            logger.warning(f"[{redact_token(token)}] {source} history fetch failed; continuing with other sources.")
            continue
        histories.append(history)
        successful_sources.append(source)

    # Preserve Stremio's native library shape when it is the only successful and
    # configured source. This keeps its added-only bucket and existing semantics.
    if sources == ["stremio"] and stremio_library is not None:
        return stremio_library

    if histories:
        merged_history = merge_watch_histories(histories)
        collection = watch_history_to_library_collection(merged_history)
        collection.source = watch_history_source_key(successful_sources)
        logger.info(
            f"[{redact_token(token)}] Built merged library from {successful_sources}: "
            f"{len(collection.loved)} loved, {len(collection.liked)} liked, "
            f"{len(collection.watched)} watched, {len(collection.added)} added"
        )
        return collection

    # Match the old behavior: if every selected external source failed but a
    # usable Stremio session exists, return Stremio as a retrying fallback. Its
    # source key differs from the configured multi-source key, so it won't mask
    # recovery of the selected providers in cache.
    if auth_key:
        logger.warning(
            f"[{redact_token(token)}] No selected history source could be fetched; "
            "falling back to Stremio library."
        )
        return await bundle.library.get_library_items(auth_key)

    return None
