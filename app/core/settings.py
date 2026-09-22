from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.poster_ratings.factory import PosterProvider


class CatalogConfig(BaseModel):
    id: str  # "watchly.rec", "watchly.theme", "watchly.item"
    name: str | None = None
    enabled: bool = True
    enabled_movie: bool = Field(default=True, description="Enable movie catalog for this configuration")
    enabled_series: bool = Field(default=True, description="Enable series catalog for this configuration")
    display_at_home: bool = Field(default=True, description="Display this catalog on home page")
    shuffle: bool = Field(default=False, description="Randomize order of items in this catalog")

    @field_validator("name", mode="before")
    @classmethod
    def _blank_name_is_none(cls, v):
        # Users can clear the rename field in the configure UI; persisting "" or
        # whitespace would produce a blank catalog row in Stremio. Normalize to
        # None so downstream code falls back to the default catalog name.
        if isinstance(v, str):
            stripped = v.strip()
            return stripped or None
        return v


class PosterRatingConfig(BaseModel):
    """Configuration for poster rating provider."""

    provider: Literal[PosterProvider.RPDB.value, PosterProvider.TOP_POSTERS.value, PosterProvider.CUSTOM.value] = Field(
        description="Provider name: 'rpdb', 'top_posters', or 'custom'"
    )
    api_key: str | None = Field(default=None, description="API key for the provider (optional for 'custom')")
    url_template: str | None = Field(
        default=None,
        description="URL template with {imdb_id}/{type}/{api_key}/{language}/{language_short} for 'custom'",
    )

    @model_validator(mode="after")
    def _check_provider_requirements(self) -> "PosterRatingConfig":
        if self.provider == PosterProvider.CUSTOM.value:
            template = (self.url_template or "").strip()
            parsed = urlparse(template)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("custom poster provider needs an http(s) url_template")
            if "{imdb_id}" not in template:
                raise ValueError("custom poster url_template must contain {imdb_id}")
        elif not (self.api_key or "").strip():
            raise ValueError(f"{self.provider} poster provider requires an api_key")
        return self


WatchHistorySource = Literal["stremio", "trakt", "simkl", "nuvio"]
WATCH_HISTORY_SOURCE_ORDER: tuple[WatchHistorySource, ...] = ("stremio", "trakt", "simkl", "nuvio")


def normalize_watch_history_sources(
    sources: list[WatchHistorySource] | tuple[WatchHistorySource, ...] | None,
    legacy_source: WatchHistorySource | None = None,
) -> list[WatchHistorySource]:
    """Return unique, valid history sources in stable provider order.

    Existing installs only have `watch_history_source`; the legacy value becomes
    a one-element source list automatically.
    """
    requested = list(sources or [])
    if not requested and legacy_source:
        requested = [legacy_source]
    if not requested:
        requested = ["stremio"]

    selected = set(requested)
    return [source for source in WATCH_HISTORY_SOURCE_ORDER if source in selected]


def watch_history_source_key(sources: list[WatchHistorySource] | tuple[WatchHistorySource, ...]) -> str:
    """Stable cache/profile source key for one or more configured providers."""
    normalized = normalize_watch_history_sources(list(sources))
    if len(normalized) == 1:
        return normalized[0]
    return "merged:" + "+".join(normalized)


LLM_PROVIDER_DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-5-mini",
    "anthropic": "claude-haiku-4-5",
    "openrouter": "openai/gpt-4o-mini",
}


class LLMConfig(BaseModel):
    """User-supplied LLM provider configuration for AI features."""

    provider: Literal["gemini", "openai", "anthropic", "openrouter"]
    api_key: str = Field(description="API key for the provider")
    model: str | None = Field(default=None, description="Model id; falls back to the provider default")

    def resolved_model(self) -> str:
        return self.model or LLM_PROVIDER_DEFAULT_MODELS[self.provider]


def get_current_year() -> int:
    return datetime.now().year


DEFAULT_YEAR_MIN = 1970


def get_default_year_max() -> int:
    return get_current_year()


def get_default_year_range() -> dict[str, int]:
    return {
        "min": DEFAULT_YEAR_MIN,
        "max": get_default_year_max(),
    }


class UserSettings(BaseModel):
    catalogs: list[CatalogConfig]
    language: str = "en-US"
    poster_rating: PosterRatingConfig | None = Field(default=None, description="Poster rating provider configuration")
    excluded_movie_genres: list[str] = Field(default_factory=list)
    excluded_series_genres: list[str] = Field(default_factory=list)
    year_min: int = Field(default=DEFAULT_YEAR_MIN, description="Minimum release year")
    year_max: int = Field(default_factory=get_default_year_max, description="Maximum release year")
    popularity: Literal["mainstream", "balanced", "gems", "all"] = Field(
        default="balanced", description="Popularity preference"
    )
    sorting_order: Literal["default", "movies_first", "series_first"] = Field(
        default="default", description="Order of movies and series catalogs"
    )
    simkl_api_key: str | None = Field(default=None, description="Simkl API Key for the user")
    llm: LLMConfig | None = Field(default=None, description="LLM provider configuration for AI features")
    # Superseded by `llm`; kept so accounts configured before multi-provider
    # support keep their AI features (see resolve_llm_config).
    gemini_api_key: str | None = Field(default=None, description="Gemini API Key for AI-powered features")
    tmdb_api_key: str | None = Field(default=None, description="TMDB API Key (used if set; else server config)")
    trakt_access_token: str | None = Field(default=None, description="Trakt OAuth access token")
    trakt_refresh_token: str | None = Field(default=None, description="Trakt OAuth refresh token")
    trakt_token_expires_at: int | None = Field(
        default=None, description="Epoch seconds when the Trakt access token expires"
    )
    simkl_access_token: str | None = Field(default=None, description="Simkl OAuth access token")
    simkl_refresh_token: str | None = Field(default=None, description="Simkl OAuth refresh token")
    simkl_token_expires_at: int | None = Field(
        default=None, description="Epoch seconds when the Simkl access token expires"
    )
    nuvio_access_token: str | None = Field(default=None, description="Nuvio Sync access token")
    nuvio_refresh_token: str | None = Field(default=None, description="Nuvio Sync refresh token")
    nuvio_token_expires_at: int | None = Field(
        default=None, description="Epoch seconds when the Nuvio access token expires"
    )
    nuvio_profile_id: int | None = Field(default=None, description="Nuvio profile index used for history")
    nuvio_profile_name: str | None = Field(default=None, description="Nuvio profile display name")
    # Legacy single-source field kept for backwards compatibility with saved
    # installs and older clients. New clients should use watch_history_sources.
    watch_history_source: WatchHistorySource = Field(
        default="stremio", description="Primary/legacy watch history source"
    )
    watch_history_sources: list[WatchHistorySource] = Field(
        default_factory=list,
        description="One or more watch history sources merged before profile building",
    )

    @model_validator(mode="after")
    def _normalize_watch_history_sources(self) -> "UserSettings":
        normalized = normalize_watch_history_sources(self.watch_history_sources, self.watch_history_source)
        self.watch_history_sources = normalized
        self.watch_history_source = normalized[0]
        return self


# Catalog descriptions for frontend
CATALOG_DESCRIPTIONS = {
    "watchly.rec": "Personalized recommendations based on your watch history, library and your reactions.",
    "watchly.item": (
        "Recommends items similar to one you recently watched or loved. The seed is picked uniformly at random"
        " from a pool of your 3 most-recent loved items + your 3 most-recent watched items. The catalog title"
        " becomes 'Because you loved <title>' or 'Because you watched <title>' depending on which bucket the"
        " seed came from."
    ),
    "watchly.creators": (
        "Recommends items from your recurring directors and lead actors — those who appear across multiple"
        " items in your library, not just one. Single-appearance creators are filtered out so the catalog"
        " actually reflects who you keep coming back to."
    ),
    "watchly.all.loved": "Recommendations based on all your loved items",
    "watchly.liked.all": "Recommendations based on all your liked items",
    "watchly.theme": (
        "Dynamic catalogs based on your favorite genres, keyword, countries and many more.Just like netflix."
        " Example: American Horror, Based on Novel or Book etc. This will show atmost 4 catalogs each for"
        " movies and series. This number can vary based on your history."
    ),
    "watchly.watchlist": (
        "Ranks titles you saved but have not watched yet by how strongly they match your Watchly taste profile."
    ),
    "watchly.recent": (
        "Builds a separate short-term taste profile from roughly your last 60 days of viewing and recommends from it."
    ),
    "watchly.hidden": (
        "High-quality, lower-popularity titles that strongly match your profile but are less likely to surface normally."
    ),
    "watchly.different": (
        "Deliberately steps outside your two dominant genres while preserving secondary tastes, quality, and creator signals."
    ),
    "watchly.newmonth": (
        "Movies and series released in the last 30 days, ranked by how well they match your taste profile."
    ),
}


def get_default_settings() -> UserSettings:
    return UserSettings(
        language="en-US",
        catalogs=[
            CatalogConfig(
                id="watchly.rec",
                name="Top Picks for You",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.item",
                name="Because you Watched/Loved",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.theme",
                name="Genre & Keyword Catalogs",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.creators",
                name="From your favourite Creators",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.all.loved",
                name="Based on what you loved",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.liked.all",
                name="Based on what you liked",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.watchlist",
                name="Watchlist Priority",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.recent",
                name="Recent Taste",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.hidden",
                name="Hidden Gems for You",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.different",
                name="Try Something Different",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.newmonth",
                name="New This Month for You",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
        ],
    )


def get_default_catalogs_for_frontend() -> list[dict]:
    """Get default catalogs formatted for frontend JavaScript."""
    settings = get_default_settings()
    catalogs = []
    for catalog in settings.catalogs:
        catalogs.append(
            {
                "id": catalog.id,
                "name": catalog.name or "",
                "enabled": catalog.enabled,
                "enabledMovie": catalog.enabled_movie,
                "enabledSeries": catalog.enabled_series,
                "display_at_home": catalog.display_at_home,
                "shuffle": catalog.shuffle,
                "description": CATALOG_DESCRIPTIONS.get(catalog.id, ""),
            }
        )
    return catalogs


def resolve_llm_config(user_settings: UserSettings | None) -> LLMConfig | None:
    """The user's LLM config, or their legacy gemini_api_key wrapped as one.

    Returns None when the user supplied no key — AI features are disabled then;
    there is deliberately no server-key fallback.
    """
    if user_settings is None:
        return None
    if user_settings.llm and user_settings.llm.api_key:
        return user_settings.llm
    if user_settings.gemini_api_key:
        return LLMConfig(provider="gemini", api_key=user_settings.gemini_api_key)
    return None


def resolve_tmdb_api_key(user_settings: UserSettings | None) -> str | None:
    """Use TMDB API key from user settings (Redis) if set, else from server config."""
    from app.core.config import settings

    if user_settings and user_settings.tmdb_api_key:
        return user_settings.tmdb_api_key
    return settings.TMDB_API_KEY


class Credentials(BaseModel):
    authKey: str
    email: str
    settings: UserSettings
