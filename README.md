# Watchly

<div align="center">

<!-- Premium Badge Collection -->
[![Version](https://img.shields.io/github/v/release/zippyy/Watchly?style=for-the-badge&logo=semver&color=6366f1)](https://github.com/zippyy/Watchly/releases)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/zippyy/Watchly?style=for-the-badge&color=f59e0b&logo=github)](https://github.com/zippyy/Watchly/stargazers)

</div>
<br/>

**Watchly** is a self-hosted **Stremio and Nuvio** recommendation addon that builds personalized movie and series recommendations from your own watch history. It reads what you've watched — from **Stremio, Trakt, Simkl, or Nuvio** — builds a numerical taste profile from it, and serves recommendation rows such as "Top Picks for You", "Because you watched …", genre and keyword catalogs, creator-based picks, and more using metadata from [TMDB](https://www.themoviedb.org/).

For Stremio, Watchly behaves like a normal catalog addon. For **Nuvio**, this fork adds **Collection Mode**: the installer creates one native **For You** Collection containing Watchly's recommendation folders instead of cluttering the Nuvio home screen with separate Watchly catalog rows. Everything is configured through the same web page and continues refreshing from your saved Watchly profile in the background.

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Catalogs](#catalogs)
- [Nuvio Collection Mode](#nuvio-collection-mode)
- [Watch history sources](#watch-history-sources)
- [Personalization](#personalization)
- [Screenshots](#screenshots)
- [Installation (Docker)](#installation-docker)
- [Unraid](#unraid)
- [Configuration reference](#configuration-reference)
- [Optional integrations](#optional-integrations)
- [Development](#development)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [Funding & support](#funding--support)
- [Acknowledgements](#acknowledgements)

## Features

- **Personalized recommendations** — a taste profile (top genres, keywords, directors, cast, eras, countries, runtime) is built from your history and drives every catalog row.
- **Merge multiple history sources** — select any combination of **Stremio**, **Trakt**, **Simkl**, and a specific **Nuvio** profile. Watchly deduplicates by IMDb ID and keeps the strongest rating, rewatch, completion, and recency signals from each provider.
- **Multiple catalog types** — Top Picks, "Because you watched/loved", dynamic genre & keyword rows, recommendations from your recurring directors and actors, and "based on everything you loved/liked".
- **Native Nuvio Collection Mode** — installing through the Watchly configure page creates/updates a single native **For You** Collection in Nuvio while keeping Watchly's backing catalogs out of normal Home/Catalog Order rows.
- **Fine-grained personalization** — discovery style (mainstream → hidden gems), release-year window, excluded genres (separately for movies and series), display language, and per-catalog enable/rename/shuffle controls.
- **Poster ratings overlay** — optionally overlay IMDb/TMDb-style ratings on posters via [RatingPosterDB](https://ratingposterdb.com/), Top Posters, or a custom template.
- **Bring your own keys** — supply your own TMDB, Simkl, or Gemini API keys, or rely on the server's.
- **Secure by design** — credentials are encrypted at rest in Redis and never appear in the manifest URL, which carries only a short opaque token.
- **Background sync** — catalogs are refreshed on a schedule so your home page is ready before you open it.
- **Fast** — aggressive Redis caching of profiles, libraries, and rendered catalogs keeps responses quick.

## How it works

1. You open the `/configure` page and connect one or more history sources (Stremio, Trakt/Simkl via OAuth, and/or Nuvio via direct browser-to-Nuvio sign-in). Stored credentials/session tokens are encrypted in Redis under a short opaque **token**. That token is embedded in your personal manifest URL.
2. Watchly fetches every selected history, deduplicates titles by IMDb ID, and merges the strongest signals: highest explicit rating, highest real watch count, highest completion, and newest watch timestamp. It then converts that merged history into a source-agnostic library — ratings ≥ 9 count as *loved*, 7–8.9 as *liked*, rewatches can act as a love signal, and unwatched Stremio library items stay in the *added* bucket.
3. From that library it builds a **taste profile**: a numerical fingerprint of your preferences across genres, keywords, people, eras, countries, and runtime.
4. When Stremio or Nuvio requests a Watchly catalog, Watchly routes the request to the matching recommendation engine, pulls candidates from TMDB (and Simkl where available), scores them against your profile, caps them for diversity, enriches them with metadata and (optionally) poster ratings, translates titles to your language, and returns standard Stremio-compatible catalog data. Nuvio Collection Mode uses those same catalog endpoints as native Collection sources.

Each user's state is keyed entirely on their token. You can add, remove, or combine history sources at any time; changing the selected source set invalidates the derived library/profile caches and rebuilds them from the new combination.

## Catalogs

You choose which of these to enable on the configure page. Each can be toggled per content type (movies / series), renamed, hidden from the home page, or shuffled.

| Catalog | ID | What it shows |
| --- | --- | --- |
| **Top Picks for You** | `watchly.rec` | Your strongest personalized recommendations, combining profile-driven TMDB discovery with picks seeded from your library. |
| **Because you watched / loved** | `watchly.item` | Titles similar to one recent item. The seed is chosen at random from your 3 most-recent loved + 3 most-recent watched items; the row title becomes "Because you loved *X*" or "Because you watched *X*" accordingly. |
| **Genre & Keyword Catalogs** | `watchly.theme` | Dynamic, Netflix-style rows built from your favorite genres, keywords, and countries (e.g. "American Horror", "Based on a Novel"). Up to ~4 rows each for movies and series, varying with your history. |
| **From your favourite Creators** | `watchly.creators` | Recommendations from directors and lead actors who recur across multiple items in your library — not one-offs. |
| **Based on what you loved** | `watchly.all.loved` | Recommendations drawn from your entire set of loved items. |
| **Based on what you liked** | `watchly.liked.all` | Recommendations drawn from your entire set of liked items. |
| **Watchlist Priority** | `watchly.watchlist` | Ranks saved-but-unwatched titles by Watchly taste fit. |
| **Recent Taste** | `watchly.recent` | Builds a short-term profile from roughly the last 60 days and recommends from what you are into lately. |
| **Hidden Gems for You** | `watchly.hidden` | Quality-filtered, lower-popularity titles ranked against your profile. |
| **Try Something Different** | `watchly.different` | Avoids your two dominant genres while preserving secondary tastes and quality signals. |
| **New This Month for You** | `watchly.newmonth` | Titles released in the last 30 days, ranked against your profile. |

## Nuvio Collection Mode

This fork includes a Nuvio-specific installation mode that presents Watchly as a native Nuvio Collection instead of a group of ordinary Home rows.

When you click **Install on Nuvio** from the Watchly configure page, Watchly:

1. Signs in directly to Nuvio from your browser and lets you choose a Nuvio profile.
2. Installs the Nuvio-specific Watchly manifest at `/{token}/nuvio/manifest.json`.
3. Marks Watchly's backing catalogs as search-only so they do not also appear as separate Nuvio Home/Catalog Order rows.
4. Pulls the profile's existing Collections, adds or replaces only the deterministic `watchly-for-you` Collection, and syncs the merged Collection list back to Nuvio.
5. Reuses Watchly's normal recommendation engines through `/{token}/nuvio/catalog/...` aliases, so recommendation generation stays identical to the standard Stremio addon.

The resulting Collection is titled **For You** and is built from the recommendation catalogs you enabled in Watchly. Static rows such as **Watchlist Priority**, **Recent Taste**, **Hidden Gems for You**, **Try Something Different**, and **New This Month for You** are combined into one Nuvio folder with Movie and Series sources when both are enabled. Stable movie/series rows such as **Top Picks for You** are combined into one folder with Movie and Series tabs, while dynamic rows such as **Because you watched/loved** and generated themes remain separate when their names or seed data differ.

Re-running **Install on Nuvio** is safe: the existing `watchly-for-you` Collection is updated instead of duplicated, and unrelated Nuvio Collections are preserved. Existing standard Watchly installs on that Nuvio profile are upgraded in place to Collection Mode.

> **Privacy:** The **Install on Nuvio** flow signs in directly from your browser to Nuvio and does not send that install session to Watchly. If you separately connect **Nuvio as a watch-history source**, your Nuvio password still never reaches Watchly; only the selected profile plus Nuvio access/refresh tokens are sent on Save and encrypted at rest so Watchly can read history later.

The regular `/{token}/manifest.json` and `/{token}/catalog/...` routes remain unchanged for Stremio and conventional addon installs.

## Watch history sources

Watchly works for users who keep their history in different places. Connect as many providers as you use, then select any combination to merge into one taste profile:

- **Stremio** — uses your Stremio library directly (requires a Stremio email/password or auth key).
- **Trakt** — connect via OAuth on the configure page; Watchly reads your watched history and ratings.
- **Simkl** — connect via OAuth on the configure page; Watchly reads your watched history and ratings.
- **Nuvio** — sign in directly to Nuvio from the configure page and choose a profile. Watchly reads the completed watched items and playback progress Nuvio Sync has stored for that profile. Nuvio does not expose an equivalent explicit rating signal here, so Watchly uses completion and recency rather than ratings.

> If that Nuvio profile is configured to use an external tracking provider such as Trakt/Simkl, Nuvio may skip writing some watched/progress events to its own Supabase sync store. Connecting that same Trakt/Simkl account to Watchly and selecting both sources fills those gaps automatically.

When the same IMDb title exists in multiple selected sources, Watchly does **not** add watch counts together (which would create fake rewatches). It uses the maximum watch count/completion, the highest explicit rating, and the newest watch timestamp.

## Personalization

All of these are set on the configure page and stored with your token:

- **Discovery style** — `mainstream`, `balanced`, `gems` (highly rated, less popular), or `all`. Controls the quality/popularity band candidates must fall in.
- **Release-year range** — restrict recommendations to a year window (default 1970–present).
- **Excluded genres** — hide genres you don't want, configured separately for movies and series.
- **Display language** — catalog titles and metadata are translated to your chosen language.
- **Sorting order** — show movies first, series first, or the default interleaving.
- **Poster ratings** — overlay ratings on posters via RPDB, Top Posters, or a custom URL template.
- **Per-catalog controls** — enable/disable, movie-only or series-only, hide from home, shuffle, and rename most catalogs.

## Screenshots

<img src="./app/static/screenshots/homepage.png" alt="Top Picks" width="800"/>

Find more screenshots [here](./app/static/screenshots/).

## Installation (Docker)

Docker is the recommended way to self-host. Watchly requires a **Redis** instance and a **TMDB API key**.

1. **Create a `docker-compose.yml`:**

   ```yaml
   services:
     redis:
       image: redis:7-alpine
       container_name: watchly-redis
       restart: unless-stopped
       volumes:
         - redis_data:/data

     watchly:
       image: ghcr.io/zippyy/Watchly:latest
       container_name: watchly
       restart: unless-stopped
       ports:
         - "8000:8000"
       env_file:
         - .env
       depends_on:
         - redis

   volumes:
     redis_data:
   ```

2. **Create a `.env` file** (see the [configuration reference](#configuration-reference) for all options):

   ```env
   # Required
   TMDB_API_KEY=your_tmdb_api_key_here
   TOKEN_SALT=generate_a_long_random_secret
   HOST_NAME=https://your-public-addon-url

   # Redis (matches the compose service name)
   REDIS_URL=redis://redis:6379/0

   # Optional — enable Trakt / Simkl (see "Optional integrations")
   # TRAKT_CLIENT_ID=
   # TRAKT_CLIENT_SECRET=
   # SIMKL_CLIENT_ID=
   # SIMKL_CLIENT_SECRET=
   ```

   `HOST_NAME` must be the public URL where the addon is reachable. It is used to build OAuth callback URLs and the manifest URL, so it has to match what Stremio (and Trakt/Simkl) will see.

3. **Start it:**

   ```bash
   docker-compose up -d
   ```

4. **Configure and install:**
   Open `http://localhost:8000/configure` (or your `HOST_NAME`), connect one or more history sources, select the sources you want merged, and pick your catalogs.
   - **Nuvio:** click **Install on Nuvio** to install/update the native **For You** Collection.
   - **Stremio:** use the generated standard manifest URL as usual.

### Unraid

A Community Applications-style template lives at [`unraid/watchly.xml`](unraid/watchly.xml).

1. Install **Redis** from Community Applications (any Redis container works).
2. On the **Docker** tab, click **Add Container**, switch to advanced view, and set the template URL to
   `https://raw.githubusercontent.com/zippyy/Watchly/main/unraid/watchly.xml` — or add
   `https://github.com/zippyy/Watchly` under *Template Repositories* and pick **Watchly** from the template list.
3. Fill in the required fields: TMDB API key, a long random token salt, the Redis URL from step 1
   (e.g. `redis://YOUR-UNRAID-IP:6379/0`), and the host name your Stremio clients will reach the addon on.
4. Start the container and open the WebUI to configure your catalogs.

## Configuration reference

All settings are environment variables. Only the first three are strictly required.

### Required

| Variable | Description |
| --- | --- |
| `TMDB_API_KEY` | TMDB API key used for metadata and discovery. Users may also supply their own key on the configure page. |
| `TOKEN_SALT` | Secret used to derive the encryption key for stored credentials. **Set a long random value** — the default `change-me` is insecure. |
| `HOST_NAME` | Public base URL of the addon (used for manifest and OAuth callback URLs). |

### Redis

| Variable | Default | Description |
| --- | --- | --- |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL. Redis is required. |
| `REDIS_MAX_CONNECTIONS` | `20` | Max Redis connections per process. |
| `REDIS_CONNECTIONS_THRESHOLD` | `100` | Background Redis-heavy jobs back off above this many total clients. |
| `REDIS_TOKEN_KEY` | `watchly:token:` | Key prefix for stored user tokens. |

### Optional integrations

| Variable | Default | Description |
| --- | --- | --- |
| `TRAKT_CLIENT_ID` / `TRAKT_CLIENT_SECRET` | — | Trakt OAuth app credentials; enable Trakt as a history source. |
| `SIMKL_CLIENT_ID` / `SIMKL_CLIENT_SECRET` | — | Simkl **AUTH V2** Server-app credentials; enable Simkl as a history source. Redirect URI: `HOST_NAME/auth/simkl/callback`. |
| `NUVIO_SUPABASE_URL` | `https://api.nuvio.tv` | Nuvio Cloud API/Sync endpoint. Override only when targeting a self-hosted Nuvio backend. |
| `NUVIO_SUPABASE_KEY` | Nuvio's documented public publishable key | Public client key used for Nuvio Cloud. Override it together with the URL for a self-hosted Nuvio backend. |

### Tuning & behavior

| Variable | Default | Description |
| --- | --- | --- |
| `PORT` | `8000` | HTTP port. |
| `ADDON_ID` | `com.bimal.watchly` | Stremio addon ID in the manifest. |
| `ADDON_NAME` | `Watchly` | Display name in the manifest. |
| `APP_ENV` | `production` | `development`, `production`, or `vercel`. |
| `TOKEN_TTL_SECONDS` | `0` | Token expiry in seconds; `0` = never expire. |
| `AUTO_UPDATE_CATALOGS` | `true` | Refresh dynamic catalogs in the background on a schedule. |
| `CATALOG_REFRESH_INTERVAL_SECONDS` | `86400` | Background refresh interval (24 h). |
| `CATALOG_CACHE_TTL` | `43200` | Rendered-catalog cache TTL (12 h). |
| `CATALOG_STALE_TTL` | `604800` | Soft-expiration fallback for cached catalogs (7 d). |
| `RECOMMENDATION_SOURCE_ITEMS_LIMIT` | `10` | Number of library items used to seed recommendations. |
| `LIBRARY_ITEMS_LIMIT` | `20` | Library item cap used in parts of the pipeline. |
| `ANNOUNCEMENT_HTML` | `""` | Optional HTML banner shown on the configure page. |
| `ALLOW_SIGNUPS` | `true` | Set to `false` to lock the instance to existing accounts; new signups are rejected. |

## Optional integrations

These are only needed if you want the corresponding feature; Watchly runs fine with just TMDB + Redis.

- **Trakt** — create an API app at [trakt.tv/oauth/applications](https://trakt.tv/oauth/applications). Set the redirect URI to `HOST_NAME/auth/trakt/callback` and put the client ID/secret in `TRAKT_CLIENT_ID` / `TRAKT_CLIENT_SECRET`.
- **Simkl** — create a **Server apps & services** app at [simkl.com/settings/developer](https://simkl.com/settings/developer). Set the redirect URI to `HOST_NAME/auth/simkl/callback` and put the credentials in `SIMKL_CLIENT_ID` / `SIMKL_CLIENT_SECRET`. Watchly uses Simkl **AUTH V2** (`/oauth2/authorize`) with PKCE and stores the returned refresh token encrypted so the 7-day access token can renew automatically.
- **Nuvio history** — no developer credentials are required. By default Watchly uses Nuvio's documented Cloud API at `https://api.nuvio.tv` with its public publishable client key. The configure page authenticates directly against that backend, lets the user choose a profile, and stores only encrypted session tokens/profile selection after Save. Self-hosted Nuvio deployments can override `NUVIO_SUPABASE_URL` and `NUVIO_SUPABASE_KEY`.
- **AI-named rows** — users configure an LLM provider (Gemini, OpenAI, Anthropic, or OpenRouter) with their own API key on the configure page; no server config required. Without one, rows fall back to deterministic names.
- **Poster ratings (RPDB)** — users enter their own [RatingPosterDB](https://ratingposterdb.com/) key on the configure page; no server config required.

## Development

Dependencies are managed with [uv](https://github.com/astral-sh/uv); a `requirements.txt` is kept in sync for non-uv environments. **Python 3.12+** is required, and a running Redis is needed for most functionality.

```bash
# Clone
git clone https://github.com/zippyy/Watchly.git
cd Watchly

# Install dependencies
uv sync

# Run the dev server (auto-reload)
uv run main.py --dev
# or
uvicorn app.core.app:app --reload
```

Create a `.env` with at least `TMDB_API_KEY`, `TOKEN_SALT`, `HOST_NAME`, and `REDIS_URL` before running. The configure UI is served at `/configure`. The **Install on Nuvio** button uses Nuvio Collection Mode; copying the standard manifest URL preserves normal Stremio-compatible behavior.

### Tests, linting, formatting

```bash
# Tests (pytest is installed into the venv on demand)
PYTHONPATH=. uv run --with pytest pytest tests/
PYTHONPATH=. uv run --with pytest pytest tests/test_catalog_endpoint.py -v

# Lint / format (also enforced by pre-commit on commit)
pre-commit run --all-files
black .      # line length 120, py312
isort .      # black profile
flake8 .     # config in setup.cfg
```

## Architecture

Watchly is a FastAPI service that speaks the Stremio addon protocol. The request flow for every authenticated endpoint is:

1. **`app/services/context.py:load_user_context`** — decrypts the token, parses settings, resolves auth, and builds the `LibraryCollection` from the configured `watch_history_source`.
2. **`app/services/recommendation/catalog_service.py`** — routes the catalog ID to a recommendation engine (Top Picks, theme, item, creators, all-loved/liked).
3. The engine's results pass through metadata enrichment, poster-ratings overlay, translation, and serialization into a Stremio catalog.

The taste-profile pipeline lives in `app/services/profile/`, all external HTTP goes through `app/core/base_client.py:BaseClient` (retries, timeouts, structured errors), and Redis (`app/services/user_cache.py`, `app/services/redis_service.py`) is the source of truth for user state.

### Project layout

```
app/
  api/            # FastAPI routers: manifest, catalog, tokens, oauth, dashboard, validation, health …
  core/           # app setup, config/settings, base HTTP client, security, constants
  models/         # Pydantic models (library, profile, …)
  services/
    profile/      # taste-profile builder
    recommendation/ # catalog routing + per-type engines, scoring, diversity, filtering
    poster_ratings/ # RPDB / Top Posters / custom overlays
    stremio/      # Stremio library + auth
    tmdb/         # TMDB client, genres, countries
    …             # trakt, simkl, gemini, translation, caching, catalog updater
  static/, templates/  # the configure UI and dashboard
```

### Key endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /configure` | Web UI for setup and catalog selection. |
| `GET /{token}/manifest.json` | Standard per-user Stremio-compatible manifest. |
| `GET /{token}/catalog/{type}/{id}.json` | Standard catalog data for a content type and catalog ID. |
| `GET /{token}/nuvio/manifest.json` | Nuvio Collection Mode manifest; keeps Watchly backing catalogs out of normal Nuvio Home rows. |
| `GET /{token}/nuvio/catalog/{type}/{id}.json` | Nuvio Collection Mode alias for the same Watchly recommendation catalog engine. |
| `GET /{token}/nuvio-collection.json` | Native Nuvio **For You** Collection definition generated from the user's enabled Watchly catalogs. |
| `POST /tokens/` | Create a token from submitted credentials/settings. |
| `GET /auth/trakt`, `GET /auth/simkl` | OAuth start; `/callback` variants complete the flow. |
| `GET /{token}/dashboard/data` | User dashboard data. |
| `GET /health`, `GET /stats` | Readiness probe and usage stats. |

## Contributing

Contributions of all sizes are welcome! This fork tracks the upstream Watchly project while carrying Nuvio-specific Collection Mode changes.

- **Small bug fixes & improvements** — open a Pull Request directly.
- **Major features & refactors** — please [open an issue](https://github.com/zippyy/Watchly/issues) first to discuss the approach. This keeps your work aligned with the project's direction and saves you time.

## Funding & support

If you find Watchly useful, please consider supporting the project:
- [Buy me Mo:Mo](https://buymemomo.com/timilsinabimal)

## Bug reports

Found a bug or have a feature request? Please [open an issue](https://github.com/zippyy/Watchly/issues) on GitHub.

## Contributors

Thank you to everyone who has contributed to the project!

<a href="https://github.com/TimilsinaBimal/watchly/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=TimilsinaBimal/watchly" />
</a>

## Acknowledgements

Special thanks to **[The Movie Database (TMDB)](https://www.themoviedb.org/)** for the rich metadata that powers Watchly's recommendations, and to **Trakt** and **Simkl** for their history APIs.
