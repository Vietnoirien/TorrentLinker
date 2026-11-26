"""Turn the extracted instance data into the preview's fixtures (fixtures.js).

    .venv/bin/python docs/specs/members-tracker-films/build_fixtures.py RAW GROUPED SETTINGS IMG_DIR

RAW is extract_fixtures.py's output, GROUPED the Catalogue releases grouped per film (seeded,
film categories of decision 18), SETTINGS the instance's `release_score` and `tracker_order`,
IMG_DIR the copied `media-artwork` files. Every release is scored with the app's own
ReleaseScore code and the Owner's active profile; the pre-selected release follows ADR-0025
(score, then Tracker order, then seeders). Library artwork is embedded small; tracker posters
stay TMDB URLs, the images the app itself caches.
"""

import base64
import io
import json
import pathlib
import re
import sys

from PIL import Image

from torrentlinker.release_score.estimate import estimate
from torrentlinker.release_score.preferences import Preferences
from torrentlinker.release_score.service import score

HERE = pathlib.Path(__file__).resolve().parent
raw = json.load(open(sys.argv[1]))
grouped = json.load(open(sys.argv[2]))
settings = json.load(open(sys.argv[3]))
images = pathlib.Path(sys.argv[4])
preferences = settings["release_score"]
order = settings.get("tracker_order") or ["c411", "tr4ker"]
threshold = Preferences.model_validate(preferences).threshold
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())


def key_of(name):
    m = re.match(r"\s*(.+?)[ ._(\[]+((?:19|20)\d\d)\b", name or "")
    return f"{norm(m.group(1))}|{m.group(2)}" if m else None


def thumb(asset, width):
    path = images / "media-artwork" / asset[len("asset:") :]
    if not path.exists():
        return ""
    image = Image.open(path).convert("RGB")
    image.thumbnail((width, width * 3 // 2))
    out = io.BytesIO()
    image.save(out, "WEBP", quality=60)
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode()


def tmdb(url, size="w342"):
    return re.sub(r"/t/p/[^/]+/", f"/t/p/{size}/", url) if url else ""


films = {}
for entry in raw["tracker"]:
    keys = {key_of(r["name"]) for r in entry["releases"]} - {None}
    key = next(iter(sorted(keys)), None) or "|".join([norm(entry["title"] or ""), entry["year"]])
    film = films.setdefault(key, {"key": key, "entry": entry, "releases": {}, "upgrade": False})
    film["upgrade"] |= entry["kind"] == "tracker-upgrade"
    for k in keys:
        for release in grouped.get(k, []):
            film["releases"][release["hash"]] = release
    for release in entry["releases"]:
        film["releases"].setdefault(release["hash"], {**release, "tracker": release.get("tracker") or "c411"})

rank = {t: i for i, t in enumerate(order)}
out = []
for film in films.values():
    entry = film["entry"]
    facts = {"title": entry["title"], "year": entry["year"], "genres": entry["genres"], "kind": "movie", "runtime": entry["runtime"] or 100}
    releases = []
    for r in film["releases"].values():
        if not r.get("seeders") or r["seeders"] <= 0:
            continue  # decision 1: only seeded releases count
        result = score(estimate(r["name"], r["size"], facts), preferences)
        if result.get("score") is None:
            continue
        releases.append(
            {
                "hash": r["hash"],
                "name": r["name"],
                "size": r["size"],
                "seeders": r["seeders"],
                "tracker": r.get("tracker") or "c411",
                "published_at": r.get("published_at"),
                "score": result["score"],
                "color": result.get("color", ""),
            }
        )
    if not releases:
        continue
    releases.sort(key=lambda r: (r["score"], -rank.get(r["tracker"], 9), r["seeders"]), reverse=True)
    out.append(
        {
            "id": "film-" + film["key"],
            "title": entry["title"],
            "original_title": entry["original_title"],
            "year": entry["year"],
            "rating": entry["rating"],
            "genres": [g for g in entry["genres"] if g != "Adventure"],
            "description": entry["overview"],
            "duration": (entry["runtime"] or 0) * 60,
            "cast": entry["cast"],
            "directors": entry["directors"],
            "poster": tmdb(entry["poster_url"]),
            "identified": bool(entry["poster_url"] or entry["overview"]),
            "in_library": film["upgrade"],
            "published_at": max(r["published_at"] or 0 for r in releases),
            "seeders": sum(r["seeders"] for r in releases),
            "releases": releases,
        }
    )
out.sort(key=lambda f: -f["published_at"])

library = []
for item in raw["library"][:150]:
    library.append(
        {
            "id": item["id"],
            "kind": "video",
            "title": item["title"],
            "year": item["year"] or "",
            "genre": item["genre"] or "",
            "description": item["description"] or "",
            "duration": float(item["duration"] or 0),
            "artwork": thumb(item["artwork"], 185),
            "series": item["series"] or "",
            "content_id": item["content_id"],
            "release": item["release"],
            "added": float(item["added"]),
        }
    )

# A phone must open the preview: each film keeps its 12 best releases and the count of the rest.
for film in out:
    film["more_releases"] = max(0, len(film["releases"]) - 12)
    film["releases"] = film["releases"][:12]
data = {"threshold": threshold, "profile": preferences.get("active"), "films": out, "library": library}
(HERE / "fixtures.js").write_text(
    "/* Generated by build_fixtures.py from a running instance (read-only). */\n"
    f"const PREVIEW_DATA = {json.dumps(data, ensure_ascii=False, separators=(',', ':'))};\n",
    encoding="utf-8",
)
print(
    f"films {len(out)}, releases {sum(len(f['releases']) for f in out)}, below threshold "
    f"{sum(f['releases'][0]['score'] < threshold for f in out)}, unidentified "
    f"{sum(not f['identified'] for f in out)}, library {len(library)}, threshold {threshold}"
)
