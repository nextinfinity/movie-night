import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import create_app, core

A = {"slug": "arrival-2016", "title": "Arrival", "year": "2016"}
B = {"slug": "alien", "title": "Alien", "year": "1979"}


class CoreTests(unittest.TestCase):
    def test_normalize_and_validate(self):
        self.assertEqual(core.normalize_users(["Alice", "https://letterboxd.com/alice/", "@bob"]), ["alice", "bob"])
        for value in [[], ["../escape"], ["https://evil.example/alice"], ["a/watchlist"], [None]]:
            with self.assertRaises(ValueError):
                core.normalize_users(value)

    def test_weighting_and_veto(self):
        pool = [(A, "alice"), (A, "bob"), (B, "alice")]
        with patch("app.core.random.choice", side_effect=lambda entries: entries[0]) as choice:
            film = core.draw(pool, set())
            self.assertEqual(choice.call_args.args[0], pool)
            self.assertEqual(film["owners"], ["alice", "bob"])
            film = core.draw(pool, {A["slug"]})
            self.assertEqual(choice.call_args.args[0], [(B, "alice")])
            self.assertEqual(film["slug"], B["slug"])
        self.assertIsNone(core.draw(pool, {A["slug"], B["slug"]}))

    def test_parser(self):
        page = '''<div data-item-name="Wallace &amp; Gromit (2005)" class="react-component poster" data-item-slug="wallace"></div>'''
        self.assertEqual(core.parse_films(page), [{"title": "Wallace & Gromit", "year": "2005", "slug": "wallace"}])

    def test_pagination_and_deduplication(self):
        first = '<div class="react-component" data-item-name="Arrival (2016)" data-item-slug="arrival-2016"></div><a href="/alice/watchlist/page/2/">2</a>'
        second = first + '<div class="react-component" data-item-name="Alien (1979)" data-item-slug="alien"></div>'
        with patch("app.core.fetch_page", side_effect=[first, second]) as fetch, patch("app.core.time.sleep"):
            self.assertEqual(core.scrape_watchlist("alice"), [A, B])
            self.assertEqual(fetch.call_count, 2)

    def test_metadata(self):
        page = '''<script type="application/ld+json">/* <![CDATA[ */
        {"@type":"Movie","image":"https://example.com/poster.jpg","description":"A visitor arrives.","datePublished":"2016-09-01","aggregateRating":{"ratingValue":4.1,"bestRating":5}}
        /* ]]> */</script><h4 class="tagline">Why are they here?</h4>'''
        metadata = core.parse_metadata(page)
        self.assertEqual(metadata["rating"], "4.1")
        self.assertEqual(metadata["year"], "2016")
        self.assertEqual(metadata["tagline"], "Why are they here?")
        self.assertEqual(core.parse_metadata('<script type="application/ld+json">invalid</script>'), {})


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATA_DIR": self.directory.name})
        self.client = self.app.test_client()
        self.scraper = patch("app.core.scrape_watchlist", side_effect=lambda user: [A, B] if user == "alice" else [A]).start()
        patch("app.core.fetch_page", return_value="").start()
        patch("app.core.random.choice", side_effect=lambda entries: entries[0]).start()
        patch("app.core.time.sleep").start()

    def tearDown(self):
        patch.stopall()
        self.directory.cleanup()

    def start(self, **options):
        return self.client.post("/api/rounds", json={"users": ["alice", "bob"], **options})

    def test_full_round_and_history(self):
        response = self.start()
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["film"]["entries"], 3)
        base = "/api/rounds/" + data["id"]
        film = self.client.post(base + "/reroll").get_json()["film"]
        self.assertEqual(film["slug"], "alien")
        self.assertEqual(film["entries"], 1)
        self.assertTrue(self.client.post(base + "/lock").get_json()["locked"])
        self.assertEqual(self.client.post(base + "/lock").status_code, 200)
        self.assertEqual(self.client.post(base + "/reroll").status_code, 409)
        with sqlite3.connect(self.directory.name + "/movie-night.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM history").fetchone()[0], 1)
        next_round = self.start().get_json()
        self.assertEqual(next_round["film"]["remaining"], 1)
        self.assertEqual(self.start(repeats=True).get_json()["film"]["remaining"], 2)
        # History survives app recreation, unlike in-memory round state.
        client = create_app({"TESTING": True, "DATA_DIR": self.directory.name}).test_client()
        self.assertEqual(client.post("/api/rounds", json={"users": ["alice"]}).get_json()["film"]["remaining"], 1)

    def test_exhaustion(self):
        data = self.start().get_json()
        url = "/api/rounds/" + data["id"] + "/reroll"
        self.client.post(url)
        self.assertIsNone(self.client.post(url).get_json()["film"])
        self.assertEqual(self.client.post(url).status_code, 409)

    def test_cache_and_refresh(self):
        self.start()
        self.start()
        self.assertEqual(self.scraper.call_count, 2)
        self.start(refresh=True)
        self.assertEqual(self.scraper.call_count, 4)

    def test_partial_failure_and_metadata_failure(self):
        self.scraper.side_effect = lambda user: [A] if user == "alice" else (_ for _ in ()).throw(LookupError("blocked"))
        with patch("app.core.fetch_page", side_effect=LookupError("offline")):
            response = self.start()
        self.assertEqual(response.status_code, 200)
        self.assertIn("blocked", response.get_json()["warnings"][0])
        self.assertEqual(response.get_json()["film"]["title"], "Arrival")

    def test_no_films(self):
        self.scraper.side_effect = lambda user: []
        self.assertEqual(self.start().status_code, 422)

    def test_default_roster_configuration(self):
        for environment, expected in [({}, []), ({"DEFAULT_USERS": ""}, []),
                                      ({"DEFAULT_USERS": "Alice, bob alice"}, ["alice", "bob"])]:
            with patch.dict(os.environ, environment, clear=True):
                client = create_app({"TESTING": True, "DATA_DIR": self.directory.name}).test_client()
                self.assertEqual(client.get("/api/config").get_json()["users"], expected)

    def test_validation_and_static(self):
        self.assertEqual(self.start(users=["../escape"]).status_code, 400)
        self.assertEqual(self.start(refresh="yes").status_code, 400)
        self.assertEqual(self.client.post("/api/rounds", json=[]).status_code, 400)
        self.assertEqual(self.client.post("/api/rounds/missing/lock").status_code, 404)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/health").get_json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
