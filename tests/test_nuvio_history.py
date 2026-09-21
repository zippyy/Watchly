import asyncio
from datetime import datetime, timezone

from app.models.history import WatchHistory
from app.services.nuvio import NuvioService


def test_nuvio_history_collapses_series_episodes_and_keeps_progress():
    service = NuvioService()

    async def watched(access_token: str, profile_id: int):
        assert access_token == "nuvio-access"
        assert profile_id == 2
        return [
            {
                "content_id": "tt1000001",
                "content_type": "movie",
                "title": "Movie A",
                "watched_at": 1_790_000_000_000,
            },
            {
                "content_id": "tt2000002",
                "content_type": "series",
                "title": "Series B",
                "season": 1,
                "episode": 1,
                "watched_at": 1_790_000_100_000,
            },
            {
                "content_id": "tt2000002",
                "content_type": "series",
                "title": "Series B",
                "season": 1,
                "episode": 2,
                "watched_at": 1_790_000_200_000,
            },
        ]

    async def progress(access_token: str, profile_id: int):
        return [
            {
                "content_id": "tt3000003",
                "content_type": "movie",
                "position": 40,
                "duration": 100,
                "last_watched": 1_790_000_300_000,
            },
            {
                # A progress mirror must not demote an already-completed title.
                "content_id": "tt1000001",
                "content_type": "movie",
                "position": 10,
                "duration": 100,
                "last_watched": 1_790_000_400_000,
            },
        ]

    service._get_watched_items = watched
    service._get_watch_progress = progress

    history = asyncio.run(service.get_history("nuvio-access", 2))

    assert isinstance(history, WatchHistory)
    assert history.source == "nuvio"
    assert {item.imdb_id for item in history.items} == {"tt1000001", "tt2000002", "tt3000003"}

    series = next(item for item in history.items if item.imdb_id == "tt2000002")
    assert series.watch_count == 1
    assert series.completion == 1.0
    assert series.last_watched == datetime.fromtimestamp(1_790_000_200, tz=timezone.utc)

    completed_movie = next(item for item in history.items if item.imdb_id == "tt1000001")
    assert completed_movie.completion == 1.0

    partial_movie = next(item for item in history.items if item.imdb_id == "tt3000003")
    assert partial_movie.completion == 0.4
    assert partial_movie.watch_count == 0

    asyncio.run(service.close())


def test_nuvio_history_ignores_non_imdb_content_ids():
    service = NuvioService()

    async def watched(access_token: str, profile_id: int):
        return [
            {"content_id": "tmdb:123", "content_type": "movie", "title": "No IMDb", "watched_at": 1},
            {"content_id": "tt4000004", "content_type": "other", "title": "Bad Type", "watched_at": 1},
        ]

    async def progress(access_token: str, profile_id: int):
        return []

    service._get_watched_items = watched
    service._get_watch_progress = progress

    history = asyncio.run(service.get_history("token", 1))
    assert history.items == []

    asyncio.run(service.close())
