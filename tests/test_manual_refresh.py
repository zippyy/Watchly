import asyncio

from fastapi.testclient import TestClient

from app.core.app import app
from app.services.dashboard import dashboard_service

client = TestClient(app)


def test_manual_refresh_forces_update_even_when_not_due(monkeypatch):
    credentials = {"last_updated": "2099-01-01T00:00:00+00:00"}
    calls = {"invalidated": 0, "force": None}

    async def resolve_alias(token):
        assert token == "account-token"
        return token

    async def get_user_data(token):
        assert token == "account-token"
        return credentials

    async def invalidate(token):
        assert token == "account-token"
        calls["invalidated"] += 1

    async def trigger(token, passed_credentials, *, force=False):
        assert token == "account-token"
        assert passed_credentials is credentials
        calls["force"] = force
        return True

    monkeypatch.setattr(dashboard_service.__class__, "refresh", dashboard_service.__class__.refresh)
    monkeypatch.setattr("app.services.dashboard.token_store.resolve_alias", resolve_alias)
    monkeypatch.setattr("app.services.dashboard.token_store.get_user_data", get_user_data)
    monkeypatch.setattr("app.services.dashboard.user_cache.invalidate_all_user_data", invalidate)
    monkeypatch.setattr("app.services.dashboard.catalog_updater.trigger_update", trigger)

    result = asyncio.run(dashboard_service.refresh("account-token"))

    assert result is True
    assert calls == {"invalidated": 1, "force": True}


def test_refresh_recommendations_endpoint(monkeypatch):
    from app.api.endpoints import dashboard as endpoint_module

    async def refresh(token):
        assert token == "abc"
        return True

    monkeypatch.setattr(endpoint_module.dashboard_service, "refresh", refresh)

    response = client.post("/abc/refresh-recommendations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "started"
    assert "Nuvio collection" in payload["detail"]
