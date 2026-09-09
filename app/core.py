"""Letterboxd scraping and the original movie_night.py weighted draw."""
import json
import random
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
REQUEST_DELAY = 0.35
CACHE_TTL = 24 * 60 * 60
# Personal rosters belong in DEFAULT_USERS environment configuration, not source.
DEFAULT_USERS = []


def normalize_users(values):
    users = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Usernames must be text.")
        user = re.sub(r"^https?://(?:www\.)?letterboxd\.com/", "", value.strip(), flags=re.I)
        user = user.strip("/@").lower()
        if not re.fullmatch(r"[a-z0-9_][a-z0-9_-]{0,63}", user):
            raise ValueError("Use a Letterboxd username or profile URL, not a display name.")
        if user not in users:
            users.append(user)
    if not 1 <= len(users) <= 30:
        raise ValueError("Add between 1 and 30 users.")
    return users


def fetch_page(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise LookupError("Letterboxd returned HTTP %s (user missing, private, or access blocked)." % exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LookupError("Couldn't reach Letterboxd. Please try again.") from exc


def parse_films(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    films = []
    for tag in soup.select(".react-component[data-item-slug][data-item-name]"):
        name = tag["data-item-name"]
        match = re.match(r"^(.*?)\s*\((\d{4})\)$", name)
        films.append({"title": match[1] if match else name,
                      "year": match[2] if match else None, "slug": tag["data-item-slug"]})
    return films


def scrape_watchlist(user):
    base = "https://letterboxd.com/%s/watchlist" % user
    first = fetch_page(base + "/")
    if any(marker in first.lower() for marker in ("just a moment...", "cf-chl-", "verify you are human")):
        raise LookupError("Letterboxd blocked this request. Try again later.")
    films = parse_films(first)
    last_page = max([int(n) for n in re.findall(r"/watchlist/page/(\d+)/", first)] or [1])
    page = 2
    while page <= last_page:
        time.sleep(REQUEST_DELAY)
        batch = parse_films(fetch_page("%s/page/%d/" % (base, page)))
        if not batch:
            break
        films.extend(batch)
        if page == last_page and len(batch) >= 28:
            last_page += 1
        page += 1
    return list({film["slug"]: film for film in films}.values())


def draw(pool, excluded):
    # Keep one entry per owner: shared films have proportionally higher odds.
    remaining = [entry for entry in pool if entry[0]["slug"] not in excluded]
    if not remaining:
        return None
    film = random.choice(remaining)[0].copy()
    film["owners"] = sorted({owner for item, owner in pool if item["slug"] == film["slug"]})
    film["entries"] = len(remaining)
    film["remaining"] = len({item["slug"] for item, _ in remaining})
    film["url"] = "https://letterboxd.com/film/%s/" % quote(film["slug"], safe="")
    return film


def parse_metadata(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    result = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text().strip().removeprefix("/* <![CDATA[ */").removesuffix("/* ]]> */").strip())
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if "@graph" in node:
                nodes.extend(node["@graph"])
            if node.get("@type") != "Movie":
                continue
            image = node.get("image")
            if isinstance(image, dict):
                image = image.get("url")
            if isinstance(image, list):
                image = image[0] if image else None
            if isinstance(image, str):
                result["poster"] = image
            result["description"] = BeautifulSoup(str(node.get("description", "")), "html.parser").get_text()
            rating = node.get("aggregateRating") or {}
            if isinstance(rating, dict) and rating.get("ratingValue") is not None:
                result["rating"] = str(rating["ratingValue"])
                result["rating_scale"] = str(rating.get("bestRating", "5"))
            if node.get("datePublished"):
                result["year"] = str(node["datePublished"])[:4]
    if not result.get("poster"):
        image = soup.select_one('meta[property="og:image"]')
        if image:
            result["poster"] = image.get("content")
    tagline = soup.select_one(".tagline")
    if tagline:
        result["tagline"] = tagline.get_text(" ", strip=True)
    if not result.get("description"):
        description = soup.select_one(".review .truncate, .film-synopsis")
        if description:
            result["description"] = description.get_text(" ", strip=True)
    if result.get("poster") and not result["poster"].startswith("https://"):
        result.pop("poster")
    return result
