# Movie Night

Your Letterboxd watchlists. One great movie night.

Combine your group's watchlists, draw a film, and pick again or lock it in with a glowing marquee celebration. Posters, film details, a midnight-blue/lavender interface, and no API key required.

## Run with Docker

Download [`compose.yaml`](compose.yaml) to your server. Optionally edit `DEFAULT_USERS` to prefill the guest list, for example `DEFAULT_USERS: "alice,bob"`. Leave it empty to add users in the browser. No `.env` file is needed.

```sh
docker compose pull
docker compose up -d
```

Open **http://<server-lan-ip>:8000** (or **http://localhost:8000** locally).

- **Image:** [`ghcr.io/nextinfinity/movie-night:latest`](https://github.com/nextinfinity/movie-night/pkgs/container/movie-night), available for AMD64 and ARM64.
- **Port:** 8000. The example publishes on all host interfaces. For a reverse proxy on the same Docker network, remove `ports` and target `http://movie-night:8000`.
- **Access:** trusted home networks only. There is no authentication; don't expose it publicly.
- **Updates:** rerun the two commands above. `latest` tracks successful builds from `main`; edit `image:` to pin a release, commit tag, or digest.

## Storage

The recommended named volume stores cache, active rounds, and accepted-pick history at **`/data`**. Preserve it across updates; `docker compose down -v` deletes it. Back up data while the app is stopped.

For a host directory instead, change these settings on the service:

```yaml
    user: "1000:1000"
    volumes:
      - ./config/movienight:/data
```

Use the UID/GID that owns your directory, and ensure it can write both the directory and existing database files. The image defaults to **10001:10001**; keep that default with the named volume. **`PUID`/`PGID` are not supported**—use `user:` instead.

The destination must be `/data`, not `/app/config`. Switching mounts doesn't migrate existing data; copy it while the service is stopped before replacing a mount.

## How picks work

The original `movie_night.py` algorithm is preserved:

- **Shared films get extra chances:** a film on three watchlists is three times as likely as one on a single list. Duplicates within one user's list count only once.
- **Pick again** removes the film entirely for the rest of that round, without adding it to history.
- **Lock it in** saves the film to shared history. Future rounds exclude it unless repeats are enabled. Nothing is changed on Letterboxd itself.
- **Start over** keeps your edited roster and begins a fresh round. Reloading the page instead returns to the default guest list; rounds aren't resumed.

All browsers share accepted history, but each draw has an independent round. Rounds expire after 24 hours. The original CLI's history isn't imported.

Watchlists and metadata are cached for **24 hours**. “Refresh watchlists” bypasses the watchlist cache. Posters, synopsis/tagline, year, and rating are shown when available; missing metadata won't prevent a draw.

### Limitations

Letterboxd scraping is unofficial. Private lists, markup changes, or bot protection may prevent loading. Failed users are reported while other users can still contribute. Caching and request delays reduce traffic, but Letterboxd's own rate limits still apply.

Large watchlists can take several minutes; a reverse proxy may need a longer request timeout.

## Local development

Python 3.9+; no frontend build step:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug --port 8000
```

Open **http://127.0.0.1:8000**. Optional settings:

```sh
DEFAULT_USERS=alice,bob DATA_DIR=./data flask --app app run --debug --port 8000
```

For a local Docker build, run `docker build -t movie-night:dev .`, temporarily set `image: movie-night:dev` in Compose, then run `docker compose up -d --pull never`.

### Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check app/static/app.js
```

GitHub Actions also builds and smoke-tests the image with both the default user and a custom UID/bind mount before publishing.

### Icon assets

`app/static/icon.svg` is the source for the header and favicon. After changing it, regenerate the PNG/ICO browser fallbacks:

```sh
.venv/bin/pip install resvg-py==0.3.2
.venv/bin/python tools/generate_icons.py
```

Generated assets are committed; no renderer is needed to run or build the app.
