# Movie Night

Your Letterboxd watchlists. One great movie night.

Add your group, draw a film, pass on it, or lock it in with a glowing marquee celebration. A midnight-blue and lavender interface with posters, film details, and no API key required.

- Combine public watchlists with **extra odds for films shared by the group**.
- Pick again without seeing the same film twice in a round.
- Remember locked-in films across nights, with an option to allow repeats.
- Edit your guest list, or prefill it with an environment variable.
- Responsive layout and reduced-motion support.

## Run with Docker

Download [`compose.yaml`](compose.yaml) and [`.env.example`](.env.example) into a directory on your server. No source checkout or local build is needed.

```sh
cp .env.example .env
```

Edit `.env`:

```dotenv
MOVIE_NIGHT_IMAGE=ghcr.io/your-owner/movie-night:latest
DEFAULT_USERS=alice,bob
BIND_ADDRESS=127.0.0.1
PORT=8000
```

Replace the image placeholder with the published GHCR package address. `alice,bob` are placeholder usernames; use your own Letterboxd users, separated by commas or whitespace, or leave `DEFAULT_USERS` empty. You can also add/remove users in the browser.

```sh
docker compose pull
docker compose up -d
```

Open **http://localhost:8000**. For access from other devices, set `BIND_ADDRESS` to your server's LAN IP (for example `192.168.1.20`), rerun `docker compose up -d`, and open `http://192.168.1.20:8000`.

**Trusted home networks only.** There is no authentication. Do not port-forward this service or expose it through a public tunnel. Use your host/router firewall to restrict access to your LAN; Docker publishing/firewall behavior varies by host.

Published images support **AMD64 and ARM64**; Docker chooses the appropriate architecture automatically. Public GHCR packages need no login. For a private package, use `docker login ghcr.io -u YOUR-USERNAME` with a classic PAT granting `read:packages` (and organization SSO authorization if required). Never put registry tokens in this repository or `.env`.

### Updates and rollback

```sh
docker compose pull
docker compose up -d
```

`:latest` tracks successful builds from `main`. For controlled updates, set `MOVIE_NIGHT_IMAGE` to a release such as `:1.0.0`, a `:sha-<full-commit-sha>` tag, or an immutable `@sha256:...` digest. To roll back, restore the previous image reference and run the same commands. Updates on the server are deliberately manual.

### Data and operations

```sh
docker compose logs -f
docker compose down       # retains cache/history
```

The named `movie-night-data` volume stores watchlist/metadata caches, active rounds, and accepted-pick history. **`docker compose down -v` deletes that data.** All browsers share accepted history, but draws have independent rounds. Rounds expire after 24 hours; reloading the page returns to the guest list rather than resuming a round.

Keep the same directory/Compose project name when updating or switching from an older deployment so Docker reuses the existing volume. You can also specify the original project with `docker compose -p <project> ...`. Back up the volume while the service is stopped before upgrades, especially if a future release changes the database schema; rolling back an image cannot undo database changes.

The container runs as non-root UID/GID 10001 with all Linux capabilities dropped and privilege escalation disabled. If replacing the named volume with a host bind mount, give that user write access. `/health` is the container health-check endpoint.

## How picks work

The selection algorithm is ported from the original `movie_night.py` CLI:

1. Fetch each user's public watchlist, deduplicating films **within each list**, not across users.
2. Build a flat pool with one entry per film per owner. A film on three watchlists has three times the chance of a film on one.
3. Exclude previously locked-in films unless repeats are enabled, then draw with `random.choice`.
4. “Pick again” removes **every entry** for that film for the rest of the round. Passing does not add to history.
5. Locking in records the film and group in persistent history. It does not modify anyone's Letterboxd account.

Start over keeps your edited roster and begins a fresh round. The original CLI's JSON history/cache is not imported.

Watchlists and metadata are cached for 24 hours. “Refresh watchlists” bypasses the watchlist cache. Failed users are reported while other users can still contribute.

Posters, tagline/synopsis, year, and average rating come from Letterboxd when available. Posters load directly from their HTTPS host, with a styled title card as a fallback. Missing metadata never prevents a draw.

### Limitations

Letterboxd scraping is unofficial. Markup changes, private lists, and bot protection can prevent loading. LAN-only hosting does **not** remove Letterboxd's own rate limits; caching and a 0.35-second request delay reduce traffic. Avoid repeatedly forcing refreshes.

Large watchlists can take several minutes. Loading uses a busy screen, not streamed progress; a reverse proxy may need a longer request timeout. Public hosting would require authentication, resource limits, and a background job queue.

## Local development

Python 3.9+ (the Docker image uses Python 3.12). No frontend build step:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug --port 8000
```

Open **http://127.0.0.1:8000**. Flask's debug server is for local use only. Edit templates, CSS, and JS directly.

Docker Compose reads `.env`; these Flask commands use shell environment variables instead:

```sh
DEFAULT_USERS=alice,bob DATA_DIR=./data flask --app app run --debug --port 8000
```

To load your own trusted, shell-compatible `.env` locally:

```sh
set -a
. ./.env
set +a
flask --app app run --debug --port 8000
```

Quote values containing spaces. Never source an untrusted environment file.

### Test a local Docker build

The standard Compose file is image-only. To test source changes in Docker:

```sh
docker build -t movie-night:dev .
MOVIE_NIGHT_IMAGE=movie-night:dev docker compose up -d --pull never
```

This uses the same configured ports and data volume as normal deployment; stop any existing deployment first or use a separate directory/Compose project for isolated testing. No separate development Compose file is required.

### Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check app/static/app.js
```

Tests cover weighting, vetoes, pagination, metadata, caching, failure handling, persistent history, and API validation using fixtures and mocked network requests. GitHub Actions also validates Compose and builds/smoke-tests the container before publishing.

## Publishing and maintenance

See [`docs/maintaining.md`](docs/maintaining.md) for GitHub setup, GHCR publishing, release tags, and dependency updates.

- `app/core.py` — scraping, metadata, weighted selection
- `app/__init__.py` — Flask API and SQLite storage
- `app/templates/`, `app/static/` — interface and animation
- `compose.yaml`, `.env.example` — published-image deployment
- `Dockerfile` — image build used locally and by CI
