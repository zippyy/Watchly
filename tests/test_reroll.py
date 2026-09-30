import asyncio

from fastapi.testclient import TestClient

from app.core.app import app
from app.services.reroll import reroll_service

client = TestClient(app)


def test_reroll_snapshots_current_batch_and_rebuilds(monkeypatch):
    calls = {"excluded": None, "invalidated": 0, "reconciled": 0, "lock_deleted": 0}

    async def manifest(_token):
        return {
            "catalogs": [
                {"type": "movie", "id": "watchly.rec", "name": "Top Picks"},
            ]
        }

    async def cached(_token, content_type, catalog_id):
        assert (content_type, catalog_id) == ("movie", "watchly.rec")
        return (
            {
                "metas": [
                    {"id": "tt0000001", "type": "movie"},
                    {"id": "tt0000002", "type": "movie"},
                ]
            },
            123,
        )

    async def set_exclusions(_token, exclusions):
        calls["excluded"] = exclusions

    async def invalidate(_token, content_type, catalog_id):
        assert (content_type, catalog_id) == ("movie", "watchly.rec")
        calls["invalidated"] += 1

    async def rebuilt(_token, content_type, catalog_id, *, trigger_auto_update=True):
        assert (content_type, catalog_id) == ("movie", "watchly.rec")
        assert trigger_auto_update is False
        return {
            "metas": [
                {"id": "tt0000003", "type": "movie"},
                {"id": "tt0000004", "type": "movie"},
            ]
        }, {}

    async def reconcile(_token, _manifest):
        calls["reconciled"] += 1
        return "updated"

    async def delete_lock(key):
        assert key == "reroll-lock"
        calls["lock_deleted"] += 1
        return True

    monkeypatch.setattr("app.services.reroll.manifest_service.get_manifest_for_token", manifest)
    monkeypatch.setattr("app.services.reroll.user_cache.get_catalog", cached)
    monkeypatch.setattr("app.services.reroll.user_cache.set_reroll_exclusions", set_exclusions)
    monkeypatch.setattr("app.services.reroll.user_cache.invalidate_catalog", invalidate)
    monkeypatch.setattr("app.services.reroll.catalog_service.get_catalog", rebuilt)
    monkeypatch.setattr("app.services.reroll.reconcile_existing_nuvio_collection", reconcile)
    monkeypatch.setattr("app.services.reroll.redis_service.delete", delete_lock)

    asyncio.run(reroll_service._run("abc", "reroll-lock"))

    assert calls["excluded"] == {
        "movie": {"watchly.rec": {"tt0000001", "tt0000002"}},
        "series": {},
    }
    assert calls["invalidated"] == 1
    assert calls["reconciled"] == 1
    assert calls["lock_deleted"] == 1


def test_reroll_endpoint_starts_background_job(monkeypatch):
    from app.api.endpoints import dashboard as endpoint_module

    async def start(token):
        assert token == "abc"
        return "started"

    monkeypatch.setattr(endpoint_module.reroll_service, "start", start)

    response = client.post("/abc/reroll-recommendations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"
    assert "fresh alternatives" in payload["detail"]


def test_reroll_endpoint_reports_existing_job(monkeypatch):
    from app.api.endpoints import dashboard as endpoint_module

    async def start(_token):
        return "already-running"

    monkeypatch.setattr(endpoint_module.reroll_service, "start", start)

    response = client.post("/abc/reroll-recommendations")

    assert response.status_code == 200
    assert response.json()["status"] == "already-running"
