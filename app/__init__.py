import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager

from flask import Flask, jsonify, render_template, request

from . import core


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(DATA_DIR=os.environ.get("DATA_DIR", "./data"), MAX_CONTENT_LENGTH=16 * 1024)
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    database = str(Path(app.config["DATA_DIR"]) / "movie-night.sqlite3")

    @contextmanager
    def connect():
        conn = sqlite3.connect(database, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, fetched REAL, value TEXT);
            CREATE TABLE IF NOT EXISTS rounds (id TEXT PRIMARY KEY, updated REAL, value TEXT);
            CREATE TABLE IF NOT EXISTS history (round_id TEXT PRIMARY KEY, slug TEXT, value TEXT);
        """)

    raw_defaults = os.environ.get("DEFAULT_USERS")
    defaults = core.normalize_users(re.split(r"[\s,]+", raw_defaults.strip())) if raw_defaults and raw_defaults.strip() else ([] if raw_defaults is not None else core.DEFAULT_USERS)

    def cached(key, loader, refresh=False):
        with connect() as db:
            row = db.execute("SELECT fetched, value FROM cache WHERE key=?", (key,)).fetchone()
        if row and not refresh and time.time() - row[0] < core.CACHE_TTL:
            return json.loads(row[1])
        value = loader()
        with connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, time.time(), json.dumps(value)))
        return value

    def present(film):
        if film is None:
            return None
        film = film.copy()
        try:
            metadata = cached("film:" + film["slug"], lambda: core.parse_metadata(core.fetch_page(film["url"])))
            film.update(metadata)
        except LookupError:
            pass  # Metadata is best-effort, never a prerequisite for the draw.
        return film

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {"users": defaults}

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @app.post("/api/rounds")
    def start():
        body = request.get_json()
        if not isinstance(body, dict) or not isinstance(body.get("users"), list):
            raise ValueError("Provide a list of users.")
        users = core.normalize_users(body["users"])
        for flag in ("refresh", "repeats"):
            if flag in body and not isinstance(body[flag], bool):
                raise ValueError("Invalid option: " + flag)
        pool, warnings, counts = [], [], {}
        for index, user in enumerate(users):
            if index:
                time.sleep(core.REQUEST_DELAY)
            try:
                films = cached("user:" + user, lambda: core.scrape_watchlist(user), body.get("refresh", False))
            except LookupError as exc:
                warnings.append("%s: %s" % (user, exc))
                continue
            counts[user] = len(films)
            if not films:
                warnings.append("%s: watchlist is empty, private, or couldn't be read." % user)
            pool.extend((film, user) for film in films)
        with connect() as db:
            excluded = [] if body.get("repeats") else [row[0] for row in db.execute("SELECT slug FROM history")]
        film = core.draw(pool, set(excluded))
        if not film:
            return jsonify(error="No eligible films. Check the watchlists or allow previously locked-in picks.", warnings=warnings), 422
        round_id = uuid.uuid4().hex
        state = {"users": users, "pool": pool, "excluded": excluded, "film": film, "locked": False}
        with connect() as db:
            db.execute("DELETE FROM rounds WHERE updated < ?", (time.time() - 86400,))
            db.execute("INSERT INTO rounds VALUES (?, ?, ?)", (round_id, time.time(), json.dumps(state)))
        return jsonify(id=round_id, film=present(film), warnings=warnings, counts=counts)

    @app.post("/api/rounds/<round_id>/<action>")
    def change(round_id, action):
        if action not in ("reroll", "lock"):
            return jsonify(error="Unknown action."), 404
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM rounds WHERE id=? AND updated >= ?", (round_id, time.time() - 86400)).fetchone()
            if not row:
                return jsonify(error="This session expired. Start over to load your group."), 404
            state = json.loads(row[0])
            if state["locked"]:
                if action == "lock":
                    return jsonify(locked=True, film=state["film"])
                return jsonify(error="This pick is already locked in."), 409
            if not state["film"]:
                return jsonify(error="You've passed on every film. Start over for a fresh round."), 409
            if action == "reroll":
                state["excluded"].append(state["film"]["slug"])
                state["film"] = core.draw(state["pool"], set(state["excluded"]))
            else:
                state["locked"] = True
                record = {**state["film"], "group": state["users"], "watched": time.strftime("%Y-%m-%d")}
                db.execute("INSERT OR IGNORE INTO history VALUES (?, ?, ?)", (round_id, record["slug"], json.dumps(record)))
            db.execute("UPDATE rounds SET updated=?, value=? WHERE id=?", (time.time(), json.dumps(state), round_id))
        return jsonify(film=present(state["film"]), locked=state["locked"])

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
