import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CATALOG_LIMIT, MAX_CATALOG_ITEMS
from app.core.settings import UserSettings
from app.models.library import LibraryCollection, StremioLibraryItem
from app.models.profile import TasteProfile
from app.services.profile.scorer import ProfileScorer
from app.services.profile.service import ProfileService
from app.services.recommendation.filtering import RecommendationFiltering, build_discover_params, filter_watched_by_imdb
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import content_type_to_mtype, resolve_tmdb_id
from app.services.tmdb.service import TMDBService


class PersonalizedCatalogService:
    """Specialized personalized rows that complement Watchly's standard Top Picks."""

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings | None = None):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings
        self.scorer = ProfileScorer()
        self.profile_service = ProfileService(
            language=getattr(user_settings, "language", "en-US"),
            tmdb_api_key=getattr(user_settings, "tmdb_api_key", None),
        )

    @staticmethod
    def _last_watched(item: StremioLibraryItem) -> datetime:
        if item.state.lastWatched:
            value = item.state.lastWatched
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if item.mtime:
            try:
                value = datetime.fromisoformat(str(item.mtime).replace("Z", "+00:00"))
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    def _recent_library(
        self,
        library_items: LibraryCollection,
        content_type: str,
        days: int = 60,
        fallback_items: int = 12,
    ) -> LibraryCollection:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        buckets = {
            "loved": [i for i in library_items.loved if i.type == content_type],
            "liked": [i for i in library_items.liked if i.type == content_type],
            "watched": [i for i in library_items.watched if i.type == content_type],
        }

        recent_ids = {item.id for items in buckets.values() for item in items if self._last_watched(item) >= cutoff}

        if not recent_ids:
            all_recent = sorted(
                [item for items in buckets.values() for item in items],
                key=self._last_watched,
                reverse=True,
            )
            recent_ids = {item.id for item in all_recent[:fallback_items]}

        return LibraryCollection(
            loved=[i for i in buckets["loved"] if i.id in recent_ids],
            liked=[i for i in buckets["liked"] if i.id in recent_ids],
            watched=[i for i in buckets["watched"] if i.id in recent_ids],
            source=f"recent:{library_items.source}",
        )

    async def _enrich_and_rank(
        self,
        candidates: list[dict[str, Any]],
        profile: TasteProfile | None,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int,
        pool_limit: int = 80,
        popularity_penalty: float = 0.0,
    ) -> list[dict[str, Any]]:
        deduped: dict[int, dict[str, Any]] = {}
        for item in candidates:
            item_id = item.get("id")
            if not isinstance(item_id, int) or item_id in watched_tmdb:
                continue
            deduped[item_id] = item

        pool = list(deduped.values())[:pool_limit]
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service,
            pool,
            content_type,
            user_settings=self.user_settings,
        )
        enriched = filter_watched_by_imdb(enriched, watched_imdb)

        if not profile:
            return enriched[:limit]

        mtype = content_type_to_mtype(content_type)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in enriched:
            score_input = dict(item)
            if item.get("releaseInfo") and not score_input.get("release_date"):
                score_input["release_date"] = f"{item['releaseInfo']}-01-01"
            try:
                score = RecommendationScoring.calculate_final_score(
                    item=score_input,
                    profile=profile,
                    scorer=self.scorer,
                    mtype=mtype,
                )
                if popularity_penalty:
                    popularity = max(float(item.get("popularity") or 0.0), 0.0)
                    score -= min(popularity / 1000.0, 0.35) * popularity_penalty
                scored.append((score, item))
            except Exception as exc:
                logger.debug(f"Failed to score specialized candidate {item.get('id')}: {exc}")

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[: min(limit, MAX_CATALOG_ITEMS)]]

    async def get_watchlist_priority(
        self,
        profile: TasteProfile | None,
        content_type: str,
        library_items: LibraryCollection,
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        added = [item for item in library_items.added if item.type == content_type]
        if not added:
            return []

        resolved = await asyncio.gather(
            *(resolve_tmdb_id(item.id, self.tmdb_service) for item in added),
            return_exceptions=True,
        )
        candidates = [{"id": tmdb_id} for tmdb_id in resolved if isinstance(tmdb_id, int)]
        return await self._enrich_and_rank(
            candidates,
            profile,
            content_type,
            watched_tmdb=set(),
            watched_imdb=set(),
            limit=limit,
            pool_limit=100,
        )

    async def get_recent_taste(
        self,
        content_type: str,
        library_items: LibraryCollection,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        recent_library = self._recent_library(library_items, content_type)
        if recent_library.is_empty():
            return []

        recent_profile = await self.profile_service._build_from_collection(
            recent_library,
            content_type,
            source=f"recent:{library_items.source}",
        )
        if not recent_profile:
            return []

        mtype = content_type_to_mtype(content_type)
        seeds = recent_library.loved + recent_library.liked + recent_library.watched
        seeds = sorted(seeds, key=self._last_watched, reverse=True)[:10]

        tasks = []
        for seed in seeds:
            tmdb_id = await resolve_tmdb_id(seed.id, self.tmdb_service)
            if tmdb_id:
                tasks.append(self.tmdb_service.get_recommendations(tmdb_id, mtype, page=1))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            candidates.extend(result.get("results", []))

        return await self._enrich_and_rank(
            candidates,
            recent_profile,
            content_type,
            watched_tmdb,
            watched_imdb,
            limit,
        )

    async def get_hidden_gems(
        self,
        profile: TasteProfile | None,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        mtype = content_type_to_mtype(content_type)
        date_params = build_discover_params(self.user_settings)
        excluded = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        if excluded:
            date_params["without_genres"] = "|".join(str(g) for g in excluded)

        tasks = [
            self.tmdb_service.get_discover(
                mtype,
                sort_by="vote_average.desc",
                page=page,
                **{
                    **date_params,
                    "vote_average.gte": 6.8,
                    "vote_count.gte": 40,
                },
            )
            for page in range(1, 4)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates = [
            item for result in results if not isinstance(result, Exception) for item in result.get("results", [])
        ]

        low_popularity = [item for item in candidates if float(item.get("popularity") or 0) <= 120.0]
        if len(low_popularity) >= max(10, limit):
            candidates = low_popularity
        else:
            candidates = sorted(candidates, key=lambda item: float(item.get("popularity") or 0))[: max(60, limit * 3)]

        return await self._enrich_and_rank(
            candidates,
            profile,
            content_type,
            watched_tmdb,
            watched_imdb,
            limit,
            popularity_penalty=0.25,
        )

    async def get_try_something_different(
        self,
        profile: TasteProfile | None,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        if not profile:
            return []

        mtype = content_type_to_mtype(content_type)
        top_genres = [genre_id for genre_id, _ in profile.get_top_genres(limit=8)]
        dominant = top_genres[:2]
        secondary = top_genres[2:8]

        excluded = set(RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type))
        excluded.update(dominant)

        params = build_discover_params(self.user_settings)
        if excluded:
            params["without_genres"] = "|".join(str(g) for g in sorted(excluded))
        if secondary:
            params["with_genres"] = "|".join(str(g) for g in secondary)
        params["vote_average.gte"] = 6.5
        params["vote_count.gte"] = 75

        tasks = [
            self.tmdb_service.get_discover(
                mtype,
                sort_by="vote_average.desc",
                page=page,
                **params,
            )
            for page in range(1, 4)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates = [
            item for result in results if not isinstance(result, Exception) for item in result.get("results", [])
        ]

        return await self._enrich_and_rank(
            candidates,
            profile,
            content_type,
            watched_tmdb,
            watched_imdb,
            limit,
        )

    async def get_new_this_month(
        self,
        profile: TasteProfile | None,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        mtype = content_type_to_mtype(content_type)
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=30)
        prefix = "primary_release_date" if mtype == "movie" else "first_air_date"

        params: dict[str, Any] = {
            f"{prefix}.gte": start.isoformat(),
            f"{prefix}.lte": today.isoformat(),
            "vote_count.gte": 5,
        }
        excluded = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        if excluded:
            params["without_genres"] = "|".join(str(g) for g in excluded)

        tasks = [
            self.tmdb_service.get_discover(
                mtype,
                sort_by="popularity.desc",
                page=page,
                **params,
            )
            for page in range(1, 4)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates = [
            item for result in results if not isinstance(result, Exception) for item in result.get("results", [])
        ]

        return await self._enrich_and_rank(
            candidates,
            profile,
            content_type,
            watched_tmdb,
            watched_imdb,
            limit,
        )
