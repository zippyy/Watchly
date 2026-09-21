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

    response = client.get("/abc/nuvio-manifest.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "com.bimal.watchly"
    assert payload["catalogs"]
    assert all(
        any(extra.get("name") == "search" and extra.get("isRequired") for extra in catalog.get("extra", []))
        for catalog in payload["catalogs"]
    )
