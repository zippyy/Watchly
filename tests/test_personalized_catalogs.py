import asyncio
from datetime import datetime, timedelta, timezone

from app.core.settings import get_default_settings
from app.models.library import LibraryCollection, StremioLibraryItem, StremioState
from app.models.profile import TasteProfile
from app.services.recommendation.personalized_catalogs import PersonalizedCatalogService


class FakeTMDB:
    def __init__(self):
        self.discover_calls = []

    async def get_discover(self, media_type, **kwargs):
        self.discover_calls.append((media_type, kwargs))
        return {
            "results": [
                {
                    "id": len(self.discover_calls),
                    "genre_ids": [18],
                    "vote_average": 7.5,
                    "vote_count": 200,
                    "popularity": 25.0,
                    "release_date": "2026-09-01",
                }
            ]
        }

    async def get_recommendations(self, tmdb_id, media_type, page=1):
        return {"results": [{"id": tmdb_id + 100, "genre_ids": [18], "vote_average": 7.5, "vote_count": 100}]}


def _item(imdb_id, *, days_ago=1, content_type="movie"):
    return StremioLibraryItem(
        _id=imdb_id,
        type=content_type,
        name=imdb_id,
        state=StremioState(lastWatched=datetime.now(timezone.utc) - timedelta(days=days_ago)),
        _mtime="",
        temp=False,
        removed=False,
    )


def test_default_settings_include_requested_five_catalogs():
    settings = get_default_settings()
    ids = {catalog.id for catalog in settings.catalogs}

    assert {
        "watchly.watchlist",
        "watchly.recent",
        "watchly.hidden",
        "watchly.different",
        "watchly.newmonth",
    }.issubset(ids)


def test_recent_library_prefers_last_60_days():
    service = PersonalizedCatalogService(FakeTMDB(), get_default_settings())
    library = LibraryCollection(
        watched=[
            _item("tt1000001", days_ago=10),
            _item("tt1000002", days_ago=90),
        ]
    )

    recent = service._recent_library(library, "movie")

    assert [item.id for item in recent.watched] == ["tt1000001"]


def test_watchlist_priority_only_uses_added_items(monkeypatch):
    service = PersonalizedCatalogService(FakeTMDB(), get_default_settings())
    library = LibraryCollection(
        added=[_item("tt2000001")],
        watched=[_item("tt2000002")],
    )
    captured = {}

    async def fake_resolve(item_id, tmdb_service):
        return 42 if item_id == "tt2000001" else 99

    async def fake_rank(candidates, *args, **kwargs):
        captured["candidates"] = candidates
        return candidates

    monkeypatch.setattr(
        "app.services.recommendation.personalized_catalogs.resolve_tmdb_id",
        fake_resolve,
    )
    monkeypatch.setattr(service, "_enrich_and_rank", fake_rank)

    result = asyncio.run(
        service.get_watchlist_priority(
            profile=TasteProfile(),
            content_type="movie",
            library_items=library,
        )
    )

    assert captured["candidates"] == [{"id": 42}]
    assert result == [{"id": 42}]


def test_try_something_different_excludes_dominant_genres(monkeypatch):
    tmdb = FakeTMDB()
    settings = get_default_settings()
    service = PersonalizedCatalogService(tmdb, settings)
    profile = TasteProfile(genre_scores={28: 10.0, 878: 9.0, 18: 7.0, 35: 5.0})

    async def fake_rank(candidates, *args, **kwargs):
        return candidates

    monkeypatch.setattr(service, "_enrich_and_rank", fake_rank)

    asyncio.run(
        service.get_try_something_different(
            profile=profile,
            content_type="movie",
            watched_tmdb=set(),
            watched_imdb=set(),
        )
    )

    assert tmdb.discover_calls
    params = tmdb.discover_calls[0][1]
    assert params["without_genres"] == "28|878"
    assert params["with_genres"] == "18|35"


def test_new_this_month_uses_30_day_release_window(monkeypatch):
    tmdb = FakeTMDB()
    service = PersonalizedCatalogService(tmdb, get_default_settings())

    async def fake_rank(candidates, *args, **kwargs):
        return candidates

    monkeypatch.setattr(service, "_enrich_and_rank", fake_rank)

    asyncio.run(
        service.get_new_this_month(
            profile=TasteProfile(),
            content_type="movie",
            watched_tmdb=set(),
            watched_imdb=set(),
        )
    )

    params = tmdb.discover_calls[0][1]
    start = datetime.fromisoformat(params["primary_release_date.gte"]).date()
    end = datetime.fromisoformat(params["primary_release_date.lte"]).date()
    assert (end - start).days == 30
    assert params["vote_count.gte"] == 5


def test_hidden_gems_uses_quality_first_discovery(monkeypatch):
    tmdb = FakeTMDB()
    service = PersonalizedCatalogService(tmdb, get_default_settings())

    async def fake_rank(candidates, *args, **kwargs):
        return candidates

    monkeypatch.setattr(service, "_enrich_and_rank", fake_rank)

    asyncio.run(
        service.get_hidden_gems(
            profile=TasteProfile(),
            content_type="movie",
            watched_tmdb=set(),
            watched_imdb=set(),
        )
    )

    params = tmdb.discover_calls[0][1]
    assert params["sort_by"] == "vote_average.desc"
    assert params["vote_average.gte"] == 6.8
    assert params["vote_count.gte"] == 40
