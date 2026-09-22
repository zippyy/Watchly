import asyncio

import app.services.manifest as manifest_mod
from app.core.settings import get_default_settings
from app.models.library import LibraryCollection


def test_cache_library_and_profiles_uses_configured_sources(monkeypatch):
    """Bootstrap caching must use the configured merged history source set."""
    captured = {}

    async def fake_fetch_library_for_sources(sources, user_settings, token, bundle, auth_key):
        captured["fetch_sources"] = sources
        return LibraryCollection(source="merged:trakt+nuvio")

    async def fake_set_library_items(token, library_items):
        captured["cached_source"] = library_items.source

    class FakeProfileService:
        def __init__(self, *args, **kwargs):
            pass

        async def build_and_cache_profile(self, *args, **kwargs):
            return None, set(), set()

    monkeypatch.setattr(manifest_mod, "fetch_library_for_sources", fake_fetch_library_for_sources)
    monkeypatch.setattr(manifest_mod.user_cache, "set_library_items", fake_set_library_items)
    monkeypatch.setattr(manifest_mod, "ProfileService", FakeProfileService)

    user_settings = get_default_settings().model_copy(
        update={
            "watch_history_source": "trakt",
            "watch_history_sources": ["trakt", "nuvio"],
        }
    )

    asyncio.run(
        manifest_mod.manifest_service.cache_library_and_profiles(
            bundle=object(), auth_key="ak", user_settings=user_settings, token="tok"
        )
    )

    assert captured["fetch_sources"] == ["trakt", "nuvio"]
    assert captured["cached_source"] == "merged:trakt+nuvio"
