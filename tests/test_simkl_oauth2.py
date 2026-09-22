import asyncio
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.core.app import app
from app.core.config import settings
from app.core.security import STORED_SECRET_SENTINEL, mask_stored_secrets
from app.services.simkl import SimklService

client = TestClient(app)


def test_simkl_auth_redirect_uses_oauth2_pkce(monkeypatch):
    monkeypatch.setattr(settings, "SIMKL_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "SIMKL_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "HOST_NAME", "https://watchly.example/")
    monkeypatch.setattr(settings, "APP_ENV", "production")

    response = client.get("/auth/simkl", follow_redirects=False)

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://simkl.com/oauth2/authorize"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://watchly.example/auth/simkl/callback"]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["media:read media:write"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 43

    assert response.cookies.get("watchly_oauth_state_simkl")
    assert response.cookies.get("watchly_oauth_pkce_simkl")


def test_simkl_callback_exchanges_with_pkce_and_returns_refresh_metadata(monkeypatch):
    monkeypatch.setattr(settings, "SIMKL_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "SIMKL_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(settings, "HOST_NAME", "https://watchly.example/")

    captured = {}

    async def exchange(code, redirect_uri, client_id, client_secret, code_verifier):
        captured.update(
            code=code,
            redirect_uri=redirect_uri,
            client_id=client_id,
            client_secret=client_secret,
            code_verifier=code_verifier,
        )
        return {
            "access_token": "simkl_at_test",
            "refresh_token": "simkl_rt_test",
            "expires_in": 604800,
        }

    async def user_settings(access_token, client_id):
        return {"account": {"id": 12345}, "user": {"name": "Nick"}}

    monkeypatch.setattr("app.api.endpoints.oauth.simkl_service.exchange_code", exchange)
    monkeypatch.setattr("app.api.endpoints.oauth.simkl_service.get_user_settings", user_settings)

    response = client.get(
        "/auth/simkl/callback",
        params={
            "code": "auth-code",
            "state": "csrf-state",
            "iss": "https://simkl.com",
        },
        cookies={
            "watchly_oauth_state_simkl": "csrf-state",
            "watchly_oauth_pkce_simkl": "pkce-verifier",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "code": "auth-code",
        "redirect_uri": "https://watchly.example/auth/simkl/callback",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "code_verifier": "pkce-verifier",
    }
    assert "simkl_at_test" in response.text
    assert "simkl_rt_test" in response.text
    assert '"expires_at"' in response.text


def test_simkl_callback_rejects_wrong_issuer(monkeypatch):
    monkeypatch.setattr(settings, "SIMKL_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "SIMKL_CLIENT_SECRET", "client-secret")

    response = client.get(
        "/auth/simkl/callback",
        params={
            "code": "auth-code",
            "state": "csrf-state",
            "iss": "https://evil.example",
        },
        cookies={
            "watchly_oauth_state_simkl": "csrf-state",
            "watchly_oauth_pkce_simkl": "pkce-verifier",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Simkl OAuth issuer. Please try connecting again."


def test_simkl_service_uses_oauth2_form_token_endpoints():
    service = SimklService()
    calls = []

    async def fake_post(path, json=None, **kwargs):
        calls.append((path, json, kwargs))
        return {
            "access_token": "simkl_at_new",
            "refresh_token": "simkl_rt_same",
            "expires_in": 604800,
        }

    service.client.post = fake_post

    asyncio.run(
        service.exchange_code(
            "code",
            "https://watchly.example/auth/simkl/callback",
            "client-id",
            "client-secret",
            "verifier",
        )
    )
    asyncio.run(service.refresh_token("simkl_rt_same", "client-id", "client-secret"))

    exchange_path, exchange_json, exchange_kwargs = calls[0]
    assert exchange_path == "/oauth2/token"
    assert exchange_json is None
    assert exchange_kwargs["data"]["grant_type"] == "authorization_code"
    assert exchange_kwargs["data"]["code_verifier"] == "verifier"
    assert exchange_kwargs["data"]["client_secret"] == "client-secret"
    assert exchange_kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    refresh_path, refresh_json, refresh_kwargs = calls[1]
    assert refresh_path == "/oauth2/token"
    assert refresh_json is None
    assert refresh_kwargs["data"]["grant_type"] == "refresh_token"
    assert refresh_kwargs["data"]["refresh_token"] == "simkl_rt_same"

    asyncio.run(service.close())


def test_simkl_refresh_token_is_masked_as_secret():
    masked = mask_stored_secrets(
        {
            "simkl_access_token": "simkl_at_secret",
            "simkl_refresh_token": "simkl_rt_secret",
        }
    )

    assert masked["simkl_access_token"] == STORED_SECRET_SENTINEL
    assert masked["simkl_refresh_token"] == STORED_SECRET_SENTINEL
