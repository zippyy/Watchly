from pathlib import Path

from app.core.config import Settings


def test_nuvio_cloud_defaults_match_documented_public_configuration():
    url = Settings.model_fields["NUVIO_SUPABASE_URL"].default
    key = Settings.model_fields["NUVIO_SUPABASE_KEY"].default

    assert url == "https://api.nuvio.tv"
    assert key == "sb_publishable_1Clq8rlTVACkdcZuqr6_AD__xUUC_EN"


def test_browser_nuvio_configuration_matches_server_defaults():
    url = Settings.model_fields["NUVIO_SUPABASE_URL"].default
    key = Settings.model_fields["NUVIO_SUPABASE_KEY"].default
    source = Path("app/static/js/modules/nuvio.js").read_text(encoding="utf-8")

    assert f"const NUVIO_BASE = '{url}';" in source
    assert f"const NUVIO_KEY = '{key}';" in source
