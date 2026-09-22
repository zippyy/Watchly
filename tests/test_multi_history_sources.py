from datetime import datetime, timezone

from app.core.settings import UserSettings, get_default_settings, watch_history_source_key
from app.models.history import WatchHistory, WatchHistoryItem
from app.services.history_merge import merge_watch_histories
from app.services.stremio.library import watch_history_to_library_collection


def _item(
    imdb_id: str,
    source: str,
    *,
    rating: float | None = None,
    watch_count: int = 1,
    completion: float = 1.0,
    last_watched: datetime | None = None,
    name: str = "Example",
):
    return WatchHistoryItem(
        imdb_id=imdb_id,
        type="movie",
        name=name,
        rating=rating,
        watch_count=watch_count,
        completion=completion,
        last_watched=last_watched,
        source=source,
    )


def test_merge_keeps_strongest_signals_without_double_counting_duplicate_watch():
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 2, 1, tzinfo=timezone.utc)

    trakt = WatchHistory(
        source="trakt",
        items=[
            _item(
                "tt1234567",
                "trakt",
                rating=9.0,
                watch_count=2,
                completion=1.0,
                last_watched=older,
                name="Rated Title",
            )
        ],
    )
    nuvio = WatchHistory(
        source="nuvio",
        items=[
            _item(
                "tt1234567",
                "nuvio",
                rating=None,
                watch_count=1,
                completion=0.65,
                last_watched=newer,
                name="Newer Title",
            )
        ],
    )

    merged = merge_watch_histories([trakt, nuvio])

    assert merged.source == "merged"
    assert len(merged.items) == 1
    item = merged.items[0]
    assert item.rating == 9.0
    assert item.watch_count == 2
    assert item.completion == 1.0
    assert item.last_watched == newer
    assert item.name == "Newer Title"


def test_merge_uses_max_watch_count_instead_of_summing_same_watch():
    stremio = WatchHistory(
        source="stremio",
        items=[_item("tt7654321", "stremio", watch_count=1)],
    )
    trakt = WatchHistory(
        source="trakt",
        items=[_item("tt7654321", "trakt", watch_count=1)],
    )

    merged = merge_watch_histories([stremio, trakt])

    assert merged.items[0].watch_count == 1


def test_watch_history_without_watch_signal_becomes_added_not_watched():
    history = WatchHistory(
        source="stremio",
        items=[
            _item(
                "tt1111111",
                "stremio",
                watch_count=0,
                completion=0.0,
            )
        ],
    )

    collection = watch_history_to_library_collection(history)

    assert [item.id for item in collection.added] == ["tt1111111"]
    assert collection.watched == []


def test_user_settings_migrates_legacy_single_source_to_list():
    defaults = get_default_settings().model_dump()
    defaults.pop("watch_history_sources", None)
    defaults["watch_history_source"] = "trakt"

    settings = UserSettings(**defaults)

    assert settings.watch_history_sources == ["trakt"]
    assert settings.watch_history_source == "trakt"


def test_multi_source_settings_are_deduped_in_stable_provider_order():
    defaults = get_default_settings().model_dump()
    defaults["watch_history_source"] = "nuvio"
    defaults["watch_history_sources"] = ["nuvio", "trakt", "nuvio", "stremio"]

    settings = UserSettings(**defaults)

    assert settings.watch_history_sources == ["stremio", "trakt", "nuvio"]
    assert settings.watch_history_source == "stremio"
    assert watch_history_source_key(settings.watch_history_sources) == "merged:stremio+trakt+nuvio"
