import re
from typing import Any

NUVIO_COLLECTION_ID = "watchly-for-you"

# These catalogs have the same semantic row for movies and series, so Nuvio can
# present both media types inside one folder. Dynamic item/theme rows are kept
# separate because their titles and backing recommendation definitions can differ.
_COMBINED_CATALOG_IDS = {
    "watchly.rec",
    "watchly.creators",
    "watchly.all.loved",
    "watchly.liked.all",
}

_EMOJI_BY_PREFIX = (
    ("watchly.rec", "🎯"),
    ("watchly.item", "👀"),
    ("watchly.all.loved", "❤️"),
    ("watchly.liked.all", "👍"),
    ("watchly.creators", "🎬"),
    ("watchly.theme", "✨"),
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "catalog"


def _emoji_for(catalog_id: str) -> str:
    for prefix, emoji in _EMOJI_BY_PREFIX:
        if catalog_id.startswith(prefix):
            return emoji
    return "✨"


def _source(addon_id: str, catalog: dict[str, Any]) -> dict[str, str]:
    return {
        "provider": "addon",
        "addonId": addon_id,
        "type": catalog["type"],
        "catalogId": catalog["id"],
    }


def build_nuvio_collection(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build Watchly's native Nuvio Collection from a tokenized manifest.

    Nuvio Collections consume addon catalogs as sources, so the existing Stremio
    catalog endpoints remain the transport while Nuvio presents them as folders.
    Folder and collection IDs are deterministic so reinstalling Watchly updates the
    existing collection rather than creating duplicates.
    """

    addon_id = str(manifest.get("id") or "com.bimal.watchly")
    catalogs = [
        catalog
        for catalog in manifest.get("catalogs", [])
        if isinstance(catalog, dict)
        and catalog.get("type") in {"movie", "series"}
        and isinstance(catalog.get("id"), str)
        and catalog.get("id")
    ]

    folders: list[dict[str, Any]] = []
    combined_done: set[str] = set()

    for catalog in catalogs:
        catalog_id = catalog["id"]
        catalog_type = catalog["type"]
        title = str(catalog.get("name") or catalog_id)

        if catalog_id in _COMBINED_CATALOG_IDS:
            if catalog_id in combined_done:
                continue
            combined_done.add(catalog_id)
            matching = [item for item in catalogs if item.get("id") == catalog_id]
            sources = [_source(addon_id, item) for item in matching]
            folder_id = f"watchly-{_slug(catalog_id.removeprefix('watchly.'))}"
        else:
            sources = [_source(addon_id, catalog)]
            folder_id = f"watchly-{catalog_type}-{_slug(catalog_id.removeprefix('watchly.'))}"

        folders.append(
            {
                "id": folder_id,
                "title": title,
                "coverEmoji": _emoji_for(catalog_id),
                "tileShape": "SQUARE",
                "hideTitle": False,
                "sources": sources,
            }
        )

    return {
        "id": NUVIO_COLLECTION_ID,
        "title": "For You",
        "pinToTop": True,
        "focusGlowEnabled": True,
        "viewMode": "TABBED_GRID",
        "showAllTab": True,
        "folders": folders,
    }
