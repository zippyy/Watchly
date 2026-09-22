from collections.abc import Iterable
from datetime import datetime, timezone

from app.models.history import WatchHistory, WatchHistoryItem


def _recency_value(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def merge_watch_histories(histories: Iterable[WatchHistory]) -> WatchHistory:
    """Merge provider histories into one title-level history keyed by IMDb ID.

    Duplicate provider records are not added together: that would turn the same
    watch synced to two services into a fake rewatch. Instead Watchly keeps the
    strongest signal each provider knows about:
      - highest explicit rating
      - highest watch count
      - highest completion
      - most recent last-watched timestamp

    This lets Trakt/Simkl contribute ratings and rewatches while Nuvio/Stremio
    can contribute newer completion/recency for the same title.
    """
    supplied = list(histories)
    merged: dict[str, WatchHistoryItem] = {}

    for history in supplied:
        for item in history.items:
            if not item.imdb_id:
                continue

            current = merged.get(item.imdb_id)
            if current is None:
                merged[item.imdb_id] = item.model_copy(deep=True)
                continue

            updates: dict = {}

            if item.rating is not None and (current.rating is None or item.rating > current.rating):
                updates["rating"] = item.rating
                updates["source"] = item.source

            if item.watch_count > current.watch_count:
                updates["watch_count"] = item.watch_count
                updates.setdefault("source", item.source)

            if item.completion > current.completion:
                updates["completion"] = item.completion
                updates.setdefault("source", item.source)

            if _recency_value(item.last_watched) > _recency_value(current.last_watched):
                updates["last_watched"] = item.last_watched
                updates["source"] = item.source
                if item.name:
                    updates["name"] = item.name

            if not current.name and item.name:
                updates["name"] = item.name

            if current.type not in {"movie", "series"} and item.type in {"movie", "series"}:
                updates["type"] = item.type

            if updates:
                merged[item.imdb_id] = current.model_copy(update=updates)

    items = sorted(
        merged.values(),
        key=lambda item: _recency_value(item.last_watched),
        reverse=True,
    )
    collection_source = supplied[0].source if len(supplied) == 1 else "merged"
    return WatchHistory(items=items, source=collection_source)
