"""Standalone Plex Custom Metadata Provider backed by the authorized TheTVDB v4 API."""
import os
import re
import sqlite3
import threading
import time
import logging
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("plex-local-tvdb")
IDENT = "tv.plex.agents.custom.sepulevrai.localtvdb"
BASE = "https://api4.thetvdb.com/v4"
KEY = os.getenv("TVDB_API_KEY", "")
PIN = os.getenv("TVDB_PIN", "")
LANG = os.getenv("TVDB_LANGUAGE", "fra")
ORDER = os.getenv("TVDB_ORDER", "default")
TTL = max(60, int(os.getenv("CACHE_TTL_SECONDS", "86400")))
DB = os.getenv("CACHE_DB", "/data/cache.sqlite3")
_lock = threading.RLock()
_token, _token_until = None, 0


def initialize():
    os.makedirs(os.path.dirname(os.path.abspath(DB)), exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, payload TEXT NOT NULL)")


def cached(key):
    import json
    with sqlite3.connect(DB) as conn:
        row = conn.execute("SELECT expires,payload FROM cache WHERE key=?", (key,)).fetchone()
    if row and row[0] > time.time():
        return json.loads(row[1])
    return None


def store(key, value):
    import json
    with sqlite3.connect(DB) as conn:
        conn.execute("REPLACE INTO cache(key,expires,payload) VALUES(?,?,?)", (key, time.time() + TTL, json.dumps(value)))


def token():
    global _token, _token_until
    with _lock:
        if _token and time.time() < _token_until:
            return _token
        if not KEY:
            raise RuntimeError("TVDB_API_KEY is missing")
        body = {"apikey": KEY}
        if PIN:
            body["pin"] = PIN
        response = requests.post(BASE + "/login", json=body, timeout=15)
        response.raise_for_status()
        _token = response.json()["data"]["token"]
        _token_until = time.time() + 25 * 86400
        return _token


def tvdb(path, params=None):
    global _token_until
    key = path + "|" + repr(sorted((params or {}).items()))
    hit = cached(key)
    if hit is not None:
        return hit
    url = BASE + path
    for attempt in range(2):
        response = requests.get(url, params=params, headers={"Authorization": "Bearer " + token()}, timeout=20)
        if response.status_code == 401 and attempt == 0:
            _token_until = 0
            continue
        response.raise_for_status()
        payload = response.json()
        store(key, payload)
        return payload
    raise RuntimeError("TheTVDB authentication failed")


def language():
    value = request.headers.get("X-Plex-Language", LANG)
    return (value.split("-")[0] or LANG).lower().replace("fr", "fra").replace("en", "eng")


def translated(obj, lang):
    translations = obj.get("translations") or {}
    if not isinstance(translations, dict):
        return {}
    names = translations.get("nameTranslations") or []
    descriptions = translations.get("overviewTranslations") or []
    def find(items):
        return next((v.get("name") or v.get("overview") or v.get("value") for v in items
                     if isinstance(v, dict) and v.get("language") == lang), None)
    return {"name": find(names), "overview": find(descriptions)}


def name(obj):
    return obj.get("name") or obj.get("seriesName") or obj.get("title") or "Unknown"


def image_url(obj):
    return obj.get("image") or obj.get("image_url") or obj.get("thumbnail")


def artwork_assets(series):
    assets = []
    for art in series.get("artworks") or []:
        url = art.get("image") or art.get("thumbnail")
        t = art.get("type")
        type_id = t.get("id") if isinstance(t, dict) else t
        kind = {2: "coverPoster", 3: "background", 5: "clearLogo"}.get(type_id)
        if url and kind:
            assets.append({"type": kind, "url": url, "alt": name(series)})
    poster = image_url(series)
    if poster and not any(a["type"] == "coverPoster" for a in assets):
        assets.insert(0, {"type": "coverPoster", "url": poster, "alt": name(series)})
    return assets


def with_images(record, assets):
    if assets:
        record["Image"] = assets
        record["thumb"] = next((a["url"] for a in assets if a["type"] in ("coverPoster", "snapshot")), record.get("thumb"))
        record["art"] = next((a["url"] for a in assets if a["type"] == "background"), record.get("art"))
    return record


def guid(kind, key):
    return IDENT + "://" + kind + "/" + key


def key_show(series_id):
    return "tvdb-show-" + str(series_id)


def key_season(series_id, season):
    return "tvdb-season-" + str(series_id) + "-" + str(season)


def key_episode(series_id, season, episode):
    return "tvdb-episode-" + str(series_id) + "-" + str(season) + "-" + str(episode)


def meta(kind, key, title, **fields):
    return {"type": kind, "ratingKey": key, "key": "/tv/library/metadata/" + key,
            "guid": guid(kind, key), "title": title, **{k: v for k, v in fields.items() if v is not None}}


def show_record(series):
    ident = series["id"]
    tr = translated(series, language())
    local = series.get("_localized") or {}
    tr = {k: local.get(k) or tr.get(k) for k in ("name", "overview")}
    poster = image_url(series)
    date = series.get("firstAired")
    result = meta("show", key_show(ident), tr.get("name") or name(series),
                  summary=tr.get("overview") or series.get("overview"),
                  year=int(date[:4]) if date and date[:4].isdigit() else None,
                  originallyAvailableAt=date, thumb=poster,
                  Guid=[{"id": "tvdb://" + str(ident)}])
    return with_images(result, artwork_assets(series))


def season_record(series_id, number, show_title="", poster=None):
    k = key_season(series_id, number)
    return meta("season", k, "Specials" if number == 0 else "Season " + str(number),
                index=number, parentRatingKey=key_show(series_id),
                parentGuid=guid("show", key_show(series_id)),
                parentKey="/tv/library/metadata/" + key_show(series_id),
                parentTitle=show_title, parentType="show", thumb=poster,
                Image=[{"type": "coverPoster", "url": poster}] if poster else None)


def episode_record(series_id, episode, show_title=""):
    season = int(episode.get("seasonNumber") or 0)
    number = int(episode.get("number") or 0)
    k = key_episode(series_id, season, number)
    date = episode.get("aired")
    still = image_url(episode)
    return meta("episode", k, name(episode), index=number, parentIndex=season,
                summary=episode.get("overview"), originallyAvailableAt=date,
                thumb=still, Image=[{"type": "snapshot", "url": still}] if still else None,
                parentRatingKey=key_season(series_id, season),
                parentKey="/tv/library/metadata/" + key_season(series_id, season),
                parentGuid=guid("season", key_season(series_id, season)), parentType="season",
                parentTitle="Season " + str(season),
                grandparentRatingKey=key_show(series_id),
                grandparentKey="/tv/library/metadata/" + key_show(series_id),
                grandparentGuid=guid("show", key_show(series_id)),
                grandparentType="show", grandparentTitle=show_title)


def show(series_id):
    series = tvdb("/series/" + str(series_id) + "/extended", {"meta": "translations"}).get("data") or {}
    lang = language()
    existing = translated(series, lang)
    # The embedded translation list may be incomplete. The dedicated API route
    # provides the authoritative translation when one exists.
    if lang != "eng" and (not existing.get("name") or not existing.get("overview")):
        try:
            response = tvdb("/series/" + str(series_id) + "/translations/" + quote(lang, safe=""))
            record = response.get("data") or {}
            if isinstance(record, list):
                record = next((x for x in record if isinstance(x, dict) and x.get("language") == lang), {})
            if isinstance(record, dict):
                series["_localized"] = {"name": record.get("name"), "overview": record.get("overview")}
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (400, 404):
                raise
    return series


def episodes(series_id):
    all_episodes = []
    seen = set()
    page = 0
    while page < 100:
        base_path = "/series/" + str(series_id) + "/episodes/" + quote(ORDER, safe="")
        try:
            result = tvdb(base_path + "/" + quote(language(), safe=""), {"page": page})
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (400, 404):
                raise
            # Some series have no translation for the requested language.
            result = tvdb(base_path, {"page": page})
        data = result.get("data") or {}
        items = data.get("episodes") or []
        for ep in items:
            if (ep.get("id"), ep.get("seasonNumber"), ep.get("number")) not in seen:
                all_episodes.append(ep)
                seen.add((ep.get("id"), ep.get("seasonNumber"), ep.get("number")))
        links = result.get("links") or {}
        if not items or not links.get("next"):
            break
        page += 1
    return all_episodes


def container(items):
    return {"MediaContainer": {"offset": 0, "size": len(items), "totalSize": len(items),
                               "identifier": IDENT, "Metadata": items}}


def paging(items):
    start = max(0, int(request.headers.get("X-Plex-Container-Start",
                        request.args.get("X-Plex-Container-Start", 0))))
    size = min(1000, max(1, int(request.headers.get("X-Plex-Container-Size",
                          request.args.get("X-Plex-Container-Size", 100)))))
    return {"MediaContainer": {"offset": start, "size": len(items[start:start+size]),
                               "totalSize": len(items), "identifier": IDENT,
                               "Metadata": items[start:start+size]}}


def parse_key(key):
    m = re.fullmatch(r"tvdb-(show|season|episode)-(\d+)(?:-(\d+))?(?:-(\d+))?", key)
    if not m:
        raise ValueError("Invalid rating key")
    kind, sid, season, ep = m.groups()
    if kind == "season" and season is None or kind == "episode" and ep is None:
        raise ValueError("Invalid rating key")
    return kind, int(sid), int(season or 0), int(ep or 0)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "configured": bool(KEY), "provider": IDENT})


@app.get("/tv")
def provider():
    return jsonify({"MediaProvider": {
        "identifier": IDENT, "title": "Plex Local TVDB", "version": "0.1.0",
        "Types": [{"type": t, "Scheme": [{"scheme": IDENT}]} for t in (2, 3, 4)],
        "Feature": [{"type": "metadata", "key": "/library/metadata"},
                    {"type": "match", "key": "/library/metadata/matches"}]
    }})


@app.post("/tv/library/metadata/matches")
def matches():
    body = request.get_json(silent=True) or {}
    try:
        title = body.get("title") or body.get("parentTitle") or body.get("grandparentTitle")
        external = str(body.get("guid") or "")
        match = re.search(r"tvdb://(\d+)", external)
        if match:
            records = [show(int(match.group(1)))]
        elif title:
            result = tvdb("/search", {"query": str(title), "type": "series"})
            records = []
            for hit in (result.get("data") or [])[:20]:
                sid = hit.get("tvdb_id") or hit.get("id")
                try:
                    if sid:
                        records.append(show(int(sid)))
                except (ValueError, requests.RequestException):
                    continue
        else:
            return jsonify(container([]))
        found = [show_record(s) for s in records]
        kind = int(body.get("type", 2))
        if kind == 3:
            found = [season_record(int(s["id"]), int(body.get("index") or 0), name(s)) for s in records]
        if kind == 4:
            found = [episode_record(int(s["id"]), next((e for e in episodes(int(s["id"]))
                       if int(e.get("seasonNumber") or 0) == int(body.get("parentIndex") or 0)
                       and int(e.get("number") or 0) == int(body.get("index") or 0)),
                       {"name": str(body.get("title") or "Episode")}), name(s)) for s in records]
        return jsonify(container(found))
    except (ValueError, requests.RequestException, RuntimeError) as exc:
        log.warning("match failure: %s", exc)
        return jsonify({"error": "TVDB lookup failed"}), 502


def fetch_metadata(key):
    kind, sid, season, number = parse_key(key)
    series = show(sid)
    if kind == "show":
        return show_record(series)
    if kind == "season":
        return season_record(sid, season, name(series), show_record(series).get("thumb"))
    item = next((e for e in episodes(sid)
                 if int(e.get("seasonNumber") or 0) == season
                 and int(e.get("number") or 0) == number), None)
    if item is None:
        return None
    return episode_record(sid, item, name(series))


@app.get("/tv/library/metadata/<key>")
def metadata(key):
    try:
        item = fetch_metadata(key)
        if item is None:
            return jsonify({"error": "not found"}), 404
        if request.args.get("includeChildren") == "1":
            children = get_children(key)
            item["Children"] = {"size": len(children), "Metadata": children}
        return jsonify(container([item]))
    except ValueError:
        return jsonify({"error": "invalid rating key"}), 400
    except (requests.RequestException, RuntimeError) as exc:
        log.warning("metadata lookup failed: %s", exc)
        return jsonify({"error": "TVDB lookup failed"}), 502


def get_children(key):
    kind, sid, season, number = parse_key(key)
    data = episodes(sid)
    if kind == "show":
        series = show(sid)
        return [season_record(sid, n, name(series), show_record(series).get("thumb")) for n in sorted({int(ep.get("seasonNumber") or 0) for ep in data})]
    if kind == "season":
        series = show(sid)
        return [episode_record(sid, ep, name(series)) for ep in data if int(ep.get("seasonNumber") or 0) == season]
    return []


@app.get("/tv/library/metadata/<key>/children")
def children(key):
    try:
        return jsonify(paging(get_children(key)))
    except ValueError:
        return jsonify({"error": "invalid rating key"}), 400
    except (requests.RequestException, RuntimeError) as exc:
        log.warning("children lookup failed: %s", exc)
        return jsonify({"error": "TVDB lookup failed"}), 502


@app.get("/tv/library/metadata/<key>/grandchildren")
def grandchildren(key):
    try:
        kind, sid, _, _ = parse_key(key)
        if kind != "show":
            return jsonify(paging([]))
        return jsonify(paging([episode_record(sid, ep, name(show(sid))) for ep in episodes(sid)]))
    except ValueError:
        return jsonify({"error": "invalid rating key"}), 400
    except (requests.RequestException, RuntimeError) as exc:
        log.warning("grandchildren lookup failed: %s", exc)
        return jsonify({"error": "TVDB lookup failed"}), 502


@app.get("/tv/library/metadata/<key>/images")
def images(key):
    try:
        item = fetch_metadata(key)
        if item is None:
            return jsonify({"error": "not found"}), 404
        images = item.get("Image") or []
        if not images and item.get("thumb"):
            kind = "snapshot" if item["type"] == "episode" else "coverPoster"
            images = [{"type": kind, "url": item["thumb"], "alt": item["title"]}]
        return jsonify({"MediaContainer": {"offset": 0, "size": len(images), "totalSize": len(images),
                                           "identifier": IDENT, "Image": images}})
    except ValueError:
        return jsonify({"error": "invalid rating key"}), 400
    except (requests.RequestException, RuntimeError):
        return jsonify({"error": "TVDB lookup failed"}), 502


initialize()
