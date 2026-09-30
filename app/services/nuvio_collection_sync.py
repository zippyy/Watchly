import hashlib
import time
from typing import Any

import httpx
from loguru import logger

from app.core.security import redact_token
from app.services.nuvio import nuvio_service
from app.services.nuvio_collection import NUVIO_COLLECTION_ID, build_nuvio_collection
from app.services.token_store import token_store


def _origin_client_id(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:20]
    return f"watchly-server-{digest}"


async def _refresh_session(token: str, credentials: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    settings_dict = credentials.get("settings") or {}
    refresh_token = str(settings_dict.get("nuvio_refresh_token") or "")
    if not refresh_token:
        return None

    try:
        data = await nuvio_service.refresh_session(refresh_token)
    except Exception as exc:
        logger.warning(f"[{redact_token(token)}] Nuvio collection session refresh failed: {exc}")
        return None

    access_token = str(data.get("access_token") or "")
    if not access_token:
        logger.warning(f"[{redact_token(token)}] Nuvio collection session refresh returned no access token")
        return None

    new_refresh = str(data.get("refresh_token") or refresh_token)
    expires_at = data.get("expires_at")
    if expires_at is None:
        expires_in = int(data.get("expires_in") or 0)
        expires_at = int(time.time()) + expires_in if expires_in else 0

    # Re-read before writing so a concurrent OAuth/provider update is not lost.
    latest = await token_store.get_user_data_fresh(token) or credentials
    latest_settings = latest.get("settings") or {}
    latest_settings["nuvio_access_token"] = access_token
    latest_settings["nuvio_refresh_token"] = new_refresh
    latest_settings["nuvio_token_expires_at"] = int(expires_at or 0)
    latest["settings"] = latest_settings
    await token_store.update_user_data(token, latest)
    return access_token, latest


async def reconcile_existing_nuvio_collection(
    token: str,
    manifest: dict[str, Any],
) -> str:
    """Update an already-installed Watchly Nuvio Collection in place.

    This is deliberately non-creating. A stored Nuvio history session alone does
    not opt a user into Collection Mode: automatic writes begin only after the
    profile already contains Watchly's deterministic collection id.
    """
    token = await token_store.resolve_alias(token)
    credentials = await token_store.get_user_data_fresh(token)
    if not credentials:
        return "no-credentials"

    settings_dict = credentials.get("settings") or {}
    access_token = str(settings_dict.get("nuvio_access_token") or "")
    refresh_token = str(settings_dict.get("nuvio_refresh_token") or "")
    profile_id = settings_dict.get("nuvio_profile_id")
    if not access_token or profile_id is None:
        return "not-connected"

    try:
        profile_id = int(profile_id)
    except (TypeError, ValueError):
        return "invalid-profile"

    # The manifest rebuild may already have refreshed the session while fetching
    # Nuvio history. Re-read above catches that. If this token is independently
    # near expiry, refresh before making the collection request.
    expires_at = int(settings_dict.get("nuvio_token_expires_at") or 0)
    if refresh_token and expires_at and time.time() >= expires_at - 300:
        refreshed = await _refresh_session(token, credentials)
        if refreshed:
            access_token, credentials = refreshed

    async def pull() -> list[dict[str, Any]]:
        return await nuvio_service.get_collections(access_token, profile_id)

    try:
        collections = await pull()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code not in (401, 403) or not refresh_token:
            raise
        refreshed = await _refresh_session(token, credentials)
        if not refreshed:
            return "auth-failed"
        access_token, credentials = refreshed
        collections = await pull()

    index = next(
        (idx for idx, item in enumerate(collections) if item.get("id") == NUVIO_COLLECTION_ID),
        None,
    )
    if index is None:
        return "not-installed"

    collection = build_nuvio_collection(manifest)
    if not collection.get("folders"):
        logger.warning(
            f"[{redact_token(token)}] Refusing to replace existing Nuvio collection with an empty definition"
        )
        return "empty"

    if collections[index] == collection:
        return "unchanged"

    merged = list(collections)
    merged[index] = collection
    await nuvio_service.push_collections(
        access_token,
        profile_id,
        merged,
        origin_client_id=_origin_client_id(token),
    )
    logger.info(
        f"[{redact_token(token)}] Automatically updated Nuvio {NUVIO_COLLECTION_ID} "
        f"({len(collection.get('folders', []))} folders)"
    )
    return "updated"
