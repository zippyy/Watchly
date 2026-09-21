from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from app.core.base_client import BaseClient
from app.core.config import settings
from app.models.history import WatchHistory, WatchHistoryItem

WATCHED_PAGE_SIZE = 900
MAX_WATCHED_PAGES = 100


class NuvioService:
    """Read Nuvio Sync profile history through Nuvio's Supabase RPC API."""

    def __init__(self) -> None:
        self.client = BaseClient(base_url=settings.NUVIO_SUPABASE_URL, timeout=15.0, max_retries=3)

    async def close(self) -> None:
        await self.client.close()

    def _headers(self, access_token: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": settings.NUVIO_SUPABASE_KEY,
            "Content-Type": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    async def get_user(self, access_token: str) -> dict[str, Any]:
        """Validate a Nuvio/Supabase access token and return its user object."""
        data = await self.client.get("/auth/v1/user", headers=self._headers(access_token))
        return data if isinstance(data, dict) else {}

    async def refresh_session(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a Supabase refresh token for a fresh Nuvio session."""
        data = await self.client.post(
            "/auth/v1/token?grant_type=refresh_token",
            json={"refresh_token": refresh_token},
            headers=self._headers(),
        )
        return data if isinstance(data, dict) else {}

    async def get_profiles(self, access_token: str) -> list[dict[str, Any]]:
        data = await self.client.post(
            "/rest/v1/rpc/sync_pull_profiles",
            json={},
            headers=self._headers(access_token),
        )
        return data if isinstance(data, list) else []

    async def get_profile(self, access_token: str, profile_id: int) -> dict[str, Any] | None:
        for profile in await self.get_profiles(access_token):
            try:
                current = int(profile.get("profile_index") or 0)
            except (TypeError, ValueError):
                continue
            if current == profile_id:
                return profile
        return None

    async def _get_watched_items(self, access_token: str, profile_id: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_WATCHED_PAGES + 1):
            batch = await self.client.post(
                "/rest/v1/rpc/sync_pull_watched_items",
                json={
                    "p_profile_id": profile_id,
                    "p_page": page,
                    "p_page_size": WATCHED_PAGE_SIZE,
                },
                headers=self._headers(access_token),
            )
            rows = batch if isinstance(batch, list) else []
            items.extend(row for row in rows if isinstance(row, dict))
            if len(rows) < WATCHED_PAGE_SIZE:
                break
        else:
            logger.warning(
                f"Nuvio watched history reached the {MAX_WATCHED_PAGES}-page safety cap "
                f"for profile {profile_id} ({len(items)} rows)"
            )
        return items

    async def _get_watch_progress(self, access_token: str, profile_id: int) -> list[dict[str, Any]]:
        data = await self.client.post(
            "/rest/v1/rpc/sync_pull_watch_progress",
            json={"p_profile_id": profile_id},
            headers=self._headers(access_token),
        )
        return data if isinstance(data, list) else []

    async def get_history(self, access_token: str, profile_id: int) -> WatchHistory:
        """Fetch completed + in-progress Nuvio history and normalize it for Watchly.

        Nuvio stores completed series watches per episode. Watchly profiles titles,
        not episodes, so all episodes collapse to their parent IMDb content_id.
        We intentionally do not treat episode count as a rewatch count; otherwise a
        normal multi-episode series would be promoted to Watchly's "loved" bucket.
        """
        watched = await self._get_watched_items(access_token, profile_id)

        # Progress improves the signal for partially watched movies/series, but a
        # non-auth failure here should not throw away a valid completed-history
        # snapshot. Authentication failures still propagate so the caller can
        # refresh or clear the Nuvio session.
        try:
            progress = await self._get_watch_progress(access_token, profile_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise
            logger.warning(f"Nuvio watch-progress fetch failed: {exc}")
            progress = []
        except Exception as exc:
            logger.warning(f"Nuvio watch-progress fetch failed: {exc}")
            progress = []

        by_id: dict[str, WatchHistoryItem] = {}

        for row in watched:
            imdb_id = str(row.get("content_id") or "")
            content_type = self._normalize_type(row.get("content_type"))
            if not imdb_id.startswith("tt") or content_type is None:
                continue

            watched_at = self._parse_epoch(row.get("watched_at"))
            existing = by_id.get(imdb_id)
            if existing is None:
                by_id[imdb_id] = WatchHistoryItem(
                    imdb_id=imdb_id,
                    type=content_type,
                    name=str(row.get("title") or ""),
                    rating=None,
                    watch_count=1,
                    completion=1.0,
                    last_watched=watched_at,
                    source="nuvio",
                )
                continue

            # Multiple series rows are normally distinct episodes, not rewatches.
            # Keep a single title-level item and only advance its recency/name.
            if watched_at and (existing.last_watched is None or watched_at > existing.last_watched):
                existing.last_watched = watched_at
            if not existing.name and row.get("title"):
                existing.name = str(row["title"])
            existing.completion = 1.0
            existing.watch_count = max(existing.watch_count, 1)

        for row in progress:
            imdb_id = str(row.get("content_id") or "")
            content_type = self._normalize_type(row.get("content_type"))
            if not imdb_id.startswith("tt") or content_type is None:
                continue

            try:
                position = max(float(row.get("position") or 0), 0.0)
                duration = max(float(row.get("duration") or 0), 0.0)
            except (TypeError, ValueError):
                position = duration = 0.0
            completion = min(position / duration, 1.0) if duration > 0 else 0.0
            if completion <= 0:
                continue

            last_watched = self._parse_epoch(row.get("last_watched"))
            existing = by_id.get(imdb_id)
            if existing is not None:
                if last_watched and (existing.last_watched is None or last_watched > existing.last_watched):
                    existing.last_watched = last_watched
                # A completed watched-item row should never be demoted by a newer
                # partial-progress mirror.
                existing.completion = max(existing.completion, completion)
                continue

            by_id[imdb_id] = WatchHistoryItem(
                imdb_id=imdb_id,
                type=content_type,
                name="",
                rating=None,
                watch_count=1 if completion >= 0.9 else 0,
                completion=completion,
                last_watched=last_watched,
                source="nuvio",
            )

        items = sorted(
            by_id.values(),
            key=lambda item: item.last_watched or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        logger.info(
            f"Nuvio history profile={profile_id}: {len(items)} title-level items "
            f"from {len(watched)} watched rows + {len(progress)} progress rows"
        )
        return WatchHistory(items=items, source="nuvio")

    @staticmethod
    def _normalize_type(value: Any) -> str | None:
        normalized = str(value or "").lower()
        if normalized == "movie":
            return "movie"
        if normalized in {"series", "show", "tv"}:
            return "series"
        return None

    @staticmethod
    def _parse_epoch(value: Any) -> datetime | None:
        try:
            raw = float(value)
        except (TypeError, ValueError):
            return None
        if raw <= 0:
            return None
        # Nuvio uses System.currentTimeMillis(), but accept seconds defensively.
        seconds = raw / 1000.0 if raw > 100_000_000_000 else raw
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None


nuvio_service = NuvioService()
