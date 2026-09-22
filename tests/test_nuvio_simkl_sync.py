import asyncio

from app.models.history import WatchHistory, WatchHistoryItem
from app.services import nuvio_simkl_sync as sync


def test_sync_adds_only_unwatched_missing_items(monkeypatch):
    async def credentials(_token):
        return {
            "settings": {
                "nuvio_access_token": "nuvio",
                "nuvio_profile_id": 1,
                "simkl_access_token": "simkl",
            }
        }

    async def alias(token):
        return token

    async def library(_token, _profile):
        return [
            {"content_id": "tt0000001", "content_type": "movie", "title": "New Movie"},
            {"content_id": "tt0000002", "content_type": "series", "title": "Watched Show"},
            {"content_id": "tt0000003", "content_type": "movie", "title": "Already Simkl"},
            {"content_id": "tt0000001", "content_type": "movie", "title": "Duplicate"},
            {"content_id": "", "content_type": "movie", "title": "Unmatched"},
        ]

    async def watched(_token, _profile):
        return [{"content_id": "tt0000002", "content_type": "series"}]

    async def simkl_history(_token, _client_id):
        return WatchHistory(
            items=[
                WatchHistoryItem(
                    imdb_id="tt0000003",
                    type="movie",
                    name="Already Simkl",
                    rating=None,
                    watch_count=0,
                    completion=0,
                    last_watched=None,
                    source="simkl",
                )
            ],
            source="simkl",
        )

    posted = {}

    async def add(_token, _client_id, *, movies=None, shows=None):
        posted["movies"] = movies or []
        posted["shows"] = shows or []
        return {"added": {"movies": len(movies or []), "shows": len(shows or [])}, "not_found": {}}

    async def cache_result(*_args, **_kwargs):
        return True

    monkeypatch.setattr(sync.token_store, "resolve_alias", alias)
    monkeypatch.setattr(sync.token_store, "get_user_data", credentials)
    monkeypatch.setattr(sync.nuvio_service, "get_library_items", library)
    monkeypatch.setattr(sync.nuvio_service, "get_watched_items", watched)
    monkeypatch.setattr(sync.simkl_service, "get_history", simkl_history)
    monkeypatch.setattr(sync.simkl_service, "add_to_plan_to_watch", add)
    monkeypatch.setattr(sync.redis_service, "set", cache_result)
    monkeypatch.setattr(sync.settings, "SIMKL_CLIENT_ID", "client-id")

    result = asyncio.run(sync.sync_nuvio_library_to_simkl("account-token"))

    assert posted == {"movies": ["tt0000001"], "shows": []}
    assert result.added == 1
    assert result.watched == 1
    assert result.skipped == 2
    assert result.unmatched == 1
    assert result.failed == 0


def test_sync_counts_simkl_not_found_as_failed(monkeypatch):
    async def credentials(_token):
        return {
            "settings": {
                "nuvio_access_token": "nuvio",
                "nuvio_profile_id": 1,
                "simkl_access_token": "simkl",
            }
        }

    async def alias(token):
        return token

    async def library(_token, _profile):
        return [{"content_id": "tt9999999", "content_type": "movie"}]

    async def watched(_token, _profile):
        return []

    async def simkl_history(_token, _client_id):
        return WatchHistory(items=[], source="simkl")

    async def add(*_args, **_kwargs):
        return {"not_found": {"movies": [{"ids": {"imdb": "tt9999999"}}]}}

    async def cache_result(*_args, **_kwargs):
        return True

    monkeypatch.setattr(sync.token_store, "resolve_alias", alias)
    monkeypatch.setattr(sync.token_store, "get_user_data", credentials)
    monkeypatch.setattr(sync.nuvio_service, "get_library_items", library)
    monkeypatch.setattr(sync.nuvio_service, "get_watched_items", watched)
    monkeypatch.setattr(sync.simkl_service, "get_history", simkl_history)
    monkeypatch.setattr(sync.simkl_service, "add_to_plan_to_watch", add)
    monkeypatch.setattr(sync.redis_service, "set", cache_result)
    monkeypatch.setattr(sync.settings, "SIMKL_CLIENT_ID", "client-id")

    result = asyncio.run(sync.sync_nuvio_library_to_simkl("account-token"))
    assert result.added == 0
    assert result.failed == 1
