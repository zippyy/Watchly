import asyncio

from fastapi.testclient import TestClient

from app.core.app import app
from app.services.nuvio_collection import NUVIO_COLLECTION_ID, build_nuvio_collection, build_nuvio_manifest

client = TestClient(app)


def _manifest():
    return {
        "id": "com.bimal.watchly",
        "catalogs": [
            {"type": "movie", "id": "watchly.rec", "name": "Top Picks for You"},
            {"type": "series", "id": "watchly.rec", "name": "Top Picks for You"},
            {"type": "movie", "id": "watchly.item.1", "name": "Because you watched Dune"},
            {"type": "series", "id": "watchly.item.1", "name": "Because you loved Severance"},
            {"type": "movie", "id": "watchly.theme.1", "name": "Cerebral Sci-Fi"},
            {"type": "series", "id": "watchly.theme.1", "name": "Prestige Mystery"},
            {"type": "movie", "id": "watchly.hidden", "name": "Hidden Gems for You"},
            {"type": "series", "id": "watchly.hidden", "name": "Hidden Gems for You"},
        ],
    }


def test_build_nuvio_collection_is_deterministic_and_combines_static_rows():
    collection = build_nuvio_collection(_manifest())

    assert collection["id"] == NUVIO_COLLECTION_ID
    assert collection["title"] == "For You"
    assert collection["pinToTop"] is True

    top_picks = next(folder for folder in collection["folders"] if folder["id"] == "watchly-rec")
    assert top_picks["title"] == "Top Picks for You"
    assert {(source["type"], source["catalogId"]) for source in top_picks["sources"]} == {
        ("movie", "watchly.rec"),
        ("series", "watchly.rec"),
    }
    assert all(source["addonId"] == "com.bimal.watchly" for source in top_picks["sources"])


def test_new_static_catalogs_combine_movie_and_series_in_nuvio():
    collection = build_nuvio_collection(_manifest())
    folders = {folder["id"]: folder for folder in collection["folders"]}

    hidden = folders["watchly-hidden"]
    assert hidden["title"] == "Hidden Gems for You"
    assert hidden["coverEmoji"] == "💎"
    assert {(source["type"], source["catalogId"]) for source in hidden["sources"]} == {
        ("movie", "watchly.hidden"),
        ("series", "watchly.hidden"),
    }


def test_dynamic_rows_are_kept_separate_by_media_type():
    collection = build_nuvio_collection(_manifest())
    folders = {folder["id"]: folder for folder in collection["folders"]}

    assert folders["watchly-movie-item-1"]["title"] == "Because you watched Dune"
    assert folders["watchly-series-item-1"]["title"] == "Because you loved Severance"
    assert folders["watchly-movie-theme-1"]["title"] == "Cerebral Sci-Fi"
    assert folders["watchly-series-theme-1"]["title"] == "Prestige Mystery"

    assert folders["watchly-movie-item-1"]["sources"] == [
        {
            "provider": "addon",
            "addonId": "com.bimal.watchly",
            "type": "movie",
            "catalogId": "watchly.item.1",
        }
    ]


def test_nuvio_collection_endpoint_uses_tokenized_manifest(monkeypatch):
    from app.api.endpoints import nuvio_collection as endpoint_module

    async def fake_manifest(token: str):
        assert token == "abc"
        return _manifest()

    monkeypatch.setattr(endpoint_module.manifest_service, "get_manifest_for_token", fake_manifest)

    response = client.get("/abc/nuvio-collection.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == NUVIO_COLLECTION_ID
    assert any(folder["id"] == "watchly-rec" for folder in payload["folders"])


def test_nuvio_collection_endpoint_rejects_bad_token():
    response = client.get("/bad.token!/nuvio-collection.json")
    assert response.status_code == 400


def test_nuvio_manifest_hides_catalog_rows_without_mutating_standard_manifest():
    manifest = _manifest()
    original_extras = [dict(catalog) for catalog in manifest["catalogs"]]

    nuvio_manifest = build_nuvio_manifest(manifest)

    assert manifest["catalogs"] == original_extras
    for catalog in nuvio_manifest["catalogs"]:
        search_extra = next(extra for extra in catalog["extra"] if extra.get("name") == "search")
        assert search_extra["isRequired"] is True


def test_nuvio_manifest_endpoint_uses_same_tokenized_catalogs(monkeypatch):
    from app.api.endpoints import manifest as endpoint_module

    async def fake_manifest(token: str):
        assert token == "abc"
        return _manifest()

    monkeypatch.setattr(endpoint_module.manifest_service, "get_manifest_for_token", fake_manifest)

    response = client.get("/abc/nuvio/manifest.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "com.bimal.watchly"
    assert payload["catalogs"]
    assert all(
        any(extra.get("name") == "search" and extra.get("isRequired") for extra in catalog.get("extra", []))
        for catalog in payload["catalogs"]
    )


def test_nuvio_catalog_alias_uses_existing_catalog_service(monkeypatch):
    from app.services.recommendation.catalog_service import catalog_service

    async def fake_get_catalog(token: str, content_type: str, catalog_id: str):
        assert token == "abc"
        assert content_type == "movie"
        assert catalog_id == "watchly.rec"
        return {"metas": [{"id": "tt1234567", "type": "movie", "name": "Example"}]}, {}

    monkeypatch.setattr(catalog_service, "get_catalog", fake_get_catalog)

    response = client.get("/abc/nuvio/catalog/movie/watchly.rec.json")

    assert response.status_code == 200
    assert response.json()["metas"][0]["id"] == "tt1234567"


def test_auto_sync_replaces_only_existing_watchly_collection(monkeypatch):
    from app.services import nuvio_collection_sync as sync_module

    credentials = {
        "settings": {
            "nuvio_access_token": "access-token",
            "nuvio_refresh_token": "refresh-token",
            "nuvio_token_expires_at": 4102444800,
            "nuvio_profile_id": 2,
        }
    }
    existing_other = {"id": "my-other-collection", "title": "Keep Me", "folders": []}
    existing_watchly = {"id": NUVIO_COLLECTION_ID, "title": "Old", "folders": [{"id": "old"}]}
    pushed = {}

    async def fake_resolve_alias(token):
        return token

    async def fake_get_user_data_fresh(token):
        return credentials

    async def fake_get_collections(access_token, profile_id):
        assert access_token == "access-token"
        assert profile_id == 2
        return [existing_other, existing_watchly]

    async def fake_push_collections(access_token, profile_id, collections, *, origin_client_id):
        pushed["access_token"] = access_token
        pushed["profile_id"] = profile_id
        pushed["collections"] = collections
        pushed["origin_client_id"] = origin_client_id

    monkeypatch.setattr(sync_module.token_store, "resolve_alias", fake_resolve_alias)
    monkeypatch.setattr(sync_module.token_store, "get_user_data_fresh", fake_get_user_data_fresh)
    monkeypatch.setattr(sync_module.nuvio_service, "get_collections", fake_get_collections)
    monkeypatch.setattr(sync_module.nuvio_service, "push_collections", fake_push_collections)

    result = asyncio.run(sync_module.reconcile_existing_nuvio_collection("account-token", _manifest()))

    assert result == "updated"
    assert pushed["profile_id"] == 2
    assert pushed["collections"][0] == existing_other
    assert pushed["collections"][1]["id"] == NUVIO_COLLECTION_ID
    assert pushed["collections"][1]["title"] == "For You"
    assert pushed["origin_client_id"].startswith("watchly-server-")
    assert "account-token" not in pushed["origin_client_id"]


def test_auto_sync_never_creates_collection_implicitly(monkeypatch):
    from app.services import nuvio_collection_sync as sync_module

    credentials = {
        "settings": {
            "nuvio_access_token": "access-token",
            "nuvio_refresh_token": "refresh-token",
            "nuvio_token_expires_at": 4102444800,
            "nuvio_profile_id": 1,
        }
    }
    pushed = False

    async def fake_resolve_alias(token):
        return token

    async def fake_get_user_data_fresh(token):
        return credentials

    async def fake_get_collections(access_token, profile_id):
        return [{"id": "unrelated", "title": "Unrelated", "folders": []}]

    async def fake_push_collections(*args, **kwargs):
        nonlocal pushed
        pushed = True

    monkeypatch.setattr(sync_module.token_store, "resolve_alias", fake_resolve_alias)
    monkeypatch.setattr(sync_module.token_store, "get_user_data_fresh", fake_get_user_data_fresh)
    monkeypatch.setattr(sync_module.nuvio_service, "get_collections", fake_get_collections)
    monkeypatch.setattr(sync_module.nuvio_service, "push_collections", fake_push_collections)

    result = asyncio.run(sync_module.reconcile_existing_nuvio_collection("account-token", _manifest()))

    assert result == "not-installed"
    assert pushed is False
