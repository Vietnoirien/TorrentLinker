"""Example library for the library-storage previews: films, posters, seeding state, tracker upgrades.

Everything is written into the real stores (media database, Catalogue-free upgrade suggestions,
artwork cache) and a FakeQbit, so the real Médias and Torrents pages draw it. Nothing is fetched.
"""

import hashlib
import io
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from tests.fake_qbit import FakeQbit
from torrentlinker.domain import LibraryFolder, Torrent
from torrentlinker.media_tracker import film_key

GB = 1000**3

# title, year, minutes, genre, colours, library release, size GB, upgrade (release, size GB) or None,
# seeding (ratio, hours) or None (in the client but stopped), disk (name, free GB)
FILMS = [
    ("The Truman Show", 1998, 103, "Comédie, Drame", ("#2c5f7a", "#8fb4c9"),
     "The.Truman.Show.1998.720p.BluRay.x264-GRP", 1.9,
     ("The.Truman.Show.1998.MULTi.1080p.BluRay.x265.AAC.5.1-TEAM", 3.1), (0.6, 31), ("/saves", 71),
     "Il est la vedette d'un show télévisé - mais il ne le sait pas. Jim Carrey a conquis à la fois les critiques et le public pour sa prestation inoubliable dans ce chef-d'œuvre de Peter Weir. Il interprète Truman Burbank, un homme dont la vie entière est un show télévisé."),
    ("Pulp Fiction", 1994, 154, "Crime, Thriller", ("#8a1f1f", "#f1c232"),
     "Pulp.Fiction.1994.720p.WEB.x264-GRP", 2.4,
     ("Pulp.Fiction.1994.MULTi.1080p.BluRay.x265.AC3-TEAM", 4.2), None, ("/saves", 71),
     "L'odyssée sanglante et burlesque de petits malfrats dans la jungle de Hollywood."),
    ("Prédestination", 2014, 97, "Science-Fiction, Thriller", ("#1d2a4a", "#9aa7c7"),
     "Predestination.2014.720p.WEB.x264-GRP", 1.6,
     ("Predestination.2014.MULTi.1080p.BluRay.x265.AAC-TEAM", 2.8), (1.4, 120), ("/windocs", 0),
     "Un agent temporel voyage dans le temps pour empêcher un crime."),
    ("Le Seigneur des anneaux : Le Retour du roi", 2003, 201, "Aventure, Fantastique", ("#5b4a2a", "#d9b56b"),
     "The.Lord.of.the.Rings.The.Return.of.the.King.2003.720p.BluRay.x264-GRP", 3.4,
     ("The.Lord.of.the.Rings.The.Return.of.the.King.2003.MULTi.1080p.BluRay.x265-TEAM", 5.5), (2.3, 144), ("/windocs", 0),
     "Les armées de Sauron déferlent sur le Gondor pendant que Frodon approche de la Montagne du Destin."),
    ("Ready Player One", 2018, 140, "Science-Fiction, Aventure", ("#3a1f6b", "#e46bd0"),
     "Ready.Player.One.2018.720p.WEB.x264-GRP", 2.2,
     ("Ready.Player.One.2018.MULTi.1080p.WEB.x265.EAC3-TEAM", 4.9), (0.9, 52), ("/saves", 71),
     "En 2045, le monde vit dans l'OASIS, un univers virtuel dont le créateur a caché un trésor."),
    ("Kung Fu Jungle", 2014, 101, "Action, Crime", ("#7a2e1b", "#e8a35a"),
     "Kung.Fu.Jungle.2014.720p.BluRay.x264-GRP", 1.7,
     ("Kung.Fu.Jungle.2014.MULTi.1080p.BluRay.x265-TEAM", 3.6), None, ("/saves", 71),
     "Un maître de kung-fu libéré de prison traque un tueur qui défie les plus grands combattants."),
    ("Quasimodo, l'âme de Paris", 2026, 96, "Animation, Drame", ("#4a3b2a", "#c9a46b"),
     "Quasimodo.2026.1080p.WEB.x265-GRP", 2.1, None, (0.2, 5), ("/saves", 71),
     "Le sonneur de Notre-Dame, version animée."),
    ("Diên Biên Phu", 1992, 135, "Guerre, Drame", ("#26402a", "#8bb08d"),
     "Dien.Bien.Phu.1992.1080p.BluRay.x264-GRP", 4.4, None, None, ("/windocs", 0),
     "La bataille de 1954, vue des deux camps."),
    ("Une histoire simple", 1978, 110, "Drame", ("#3b3b45", "#b7b2a5"),
     "Une.histoire.simple.1978.1080p.WEB.x264-GRP", 2.8, None, (1.1, 90), ("/saves", 71),
     "Marie, quarante ans, divorcée, doit décider de la suite de sa vie."),
    ("Ils sont grands, ces petits", 1979, 100, "Comédie", ("#2d4f5e", "#e5c07b"),
     "Ils.sont.grands.ces.petits.1979.720p.WEB.x264-GRP", 1.5, None, (0.5, 20), ("/saves", 71),
     "Une bande d'enfants prend le pouvoir."),
    ("22 Jump Street", 2014, 112, "Comédie, Action", ("#7a1f3a", "#f0a060"),
     "22.Jump.Street.2014.1080p.BluRay.x264-GRP", 3.9, None, (0.7, 40), ("/windocs", 0),
     "Deux flics infiltrent un campus."),
    ("65 : La Terre d'avant", 2023, 93, "Science-Fiction, Action", ("#18323a", "#6fb3a5"),
     "65.2023.1080p.WEB.x265-GRP", 2.6, None, (0.4, 14), ("/saves", 71),
     "Un pilote s'écrase sur une planète préhistorique."),
    ("Transformers : L'Âge de l'extinction", 2014, 165, "Action, Science-Fiction", ("#4b2a14", "#d98e3f"),
     "Transformers.Age.of.Extinction.2014.1080p.BluRay.x264-GRP", 5.1, None, (3.2, 400), ("/windocs", 0),
     "Quatre ans après Chicago, les Transformers sont traqués."),
    ("Street Fighter", 2026, 117, "Action", ("#8a3a1f", "#ffd166"),
     "Street.Fighter.2026.1080p.WEB.x265-GRP", 3.0, None, (0.1, 2), ("/saves", 71),
     "Le tournoi mondial de combat."),
]


def poster(title, colours):
    """A coloured gradient poster with the title: no outside image."""
    width, height = 600, 900
    top, bottom = (tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in colours)
    picture = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(picture)
    for y in range(height):
        mix = y / height
        draw.line([(0, y), (width, y)], fill=tuple(int(a + (b - a) * mix) for a, b in zip(top, bottom)))
    font = None
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(path, 62)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    lines, line = [], ""
    for word in title.split():
        if len(line + " " + word) > 13 and line:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    lines.append(line)
    y = height // 2 - 40 * len(lines)
    for text in lines:
        width_text = draw.textlength(text, font=font)
        draw.text(((width - width_text) / 2 + 3, y + 3), text, fill=(0, 0, 0), font=font)
        draw.text(((width - width_text) / 2, y), text, fill=(255, 255, 255), font=font)
        y += 78
    out = io.BytesIO()
    picture.save(out, "PNG")
    return out.getvalue()


def sha(text):
    return hashlib.sha1(text.encode()).hexdigest()


def fixture_json():
    """What replace.js needs beside the real stores: seeding and disks per library film."""
    out = {"films": {}}
    for title, year, _m, _g, _c, name, size, upgrade, seed, disk, _d in FILMS:
        out["films"][title] = {
            "year": year,
            "old": {"name": name, "size": size, "seed": {"ratio": seed[0], "hours": seed[1]} if seed else None,
                    "hash": sha("old" + name)},
            "folder": f"{disk[0]}/Films",
            "disk": disk[0],
            "free": disk[1],
            "upgrade": {"name": upgrade[0], "size": upgrade[1]} if upgrade else None,
        }
    return out


def seed(app, setup, client: FakeQbit, root: Path):
    """Write the library, its posters, the seeding clients and the tracker upgrades."""
    media = app.state.assistant.agent.media
    films = root / "Films"
    films.mkdir()
    for title, year, _m, _g, _c, name, size, _u, seeding, _d, _desc in FILMS:
        folder = films / name
        folder.mkdir()
        with (folder / f"{name}.mkv").open("wb") as video:
            video.truncate(int(size * GB))  # sparse: the size is real, the disk use is not
    setup.settings.library_folders = [LibraryFolder(films)]
    setup.save()
    # The scan reads the folders; the network steps are off.
    with (
        patch.object(type(media), "enrich", lambda *a, **k: "ok"),
        patch.object(type(media), "tracker_refresh", lambda *a, **k: "complete"),
        patch.object(type(media), "films_refresh", lambda *a, **k: None),
    ):
        media.scan("default", threading.Event(), lambda _p: None)
    now = time.time()
    by_file = {f"{n}.mkv": (i, row) for i, row in enumerate(FILMS) for n in [row[5]]}
    with media.lock, media.db:
        for row in media.db.execute("SELECT id, path, body FROM media_items").fetchall():
            index, film = by_file[Path(row["path"]).name]
            title, year, minutes, genre, colours, name, size, _u, _s, _d, desc = film
            body = json.loads(row["body"]) | {
                "title": title, "year": str(year), "genre": genre, "description": desc,
                "duration": minutes * 60, "language": "MULTI", "rating": round(6 + (index % 30) / 10, 3),
                "artwork": media.cache_artwork(poster(title, colours)), "release": name,
            }
            media.db.execute(
                "UPDATE media_items SET body=?, size=?, added=? WHERE id=?",
                (json.dumps(body), int(size * GB), now - index * 3600, row["id"]),
            )
        library = {r["id"]: json.loads(r["body"]) for r in media.db.execute("SELECT id, body FROM media_items")}
    # The torrents behind the files: seeding with ratio and time, one stopped.
    for title, year, minutes, genre, _c, name, size, upgrade, seeding, _d, desc in FILMS:
        h = sha("old" + name)
        client.by_hash[h] = Torrent(
            h, name, films, files={f"{name}/{name}.mkv": int(size * GB)},
            tags=frozenset(), progress=1.0, state="uploading" if seeding else "stoppedUP",
            seeding_time=(seeding[1] * 3600 if seeding else 0), size=int(size * GB),
            category="Films", ratio=(seeding[0] if seeding else 0.0), upload_rate=0,
            trackers=("https://c411.org/announce",), tracker="https://c411.org/announce",
        )
    # The tracker's better versions, as the daily local scoring would have saved them.
    for index, (title, year, minutes, genre, _c, name, size, upgrade, *_rest) in enumerate(FILMS):
        if not upgrade:
            continue
        item = next(i for i, b in library.items() if b["title"] == title)
        entry = {
            "at": now, "title": title, "year": str(year),
            "releases": [{"hash": sha("new" + upgrade[0]), "name": upgrade[0], "size": int(upgrade[1] * GB),
                          "seeders": 40 - index * 3, "category": 2030}],
            "files": [{"name": name + ".mkv", "size": int(size * GB)}],
            "library_id": item,
            "facts": {"title": title, "year": str(year), "runtime": minutes, "kind": "movie", "tags": [],
                      "genres": [g.strip() for g in genre.split(",")], "rating": library[item]["rating"],
                      "overview": FILMS[index][10]},
        }
        media._tracker_save("default", "tracker-upgrade", film_key(title, str(year)), entry)
    with media.lock, media.db:
        media.db.execute("INSERT OR REPLACE INTO media_options VALUES (?,?)",
                         ("tracker-status:default", json.dumps("complete")))
        media.db.execute("INSERT OR REPLACE INTO media_options VALUES (?,?)",
                         ("tracker-run:default", json.dumps(now + 10**7)))


# ---- Fichiers / Disques / Organisation: data for screens that have no backend yet --------------------

# Where each film lives: the films on /windocs (full) give the "disk nearly full" Replace scenario.
DISKS = [
    {"id": "d1", "name": "/saves", "mount": "/saves", "fs": "ext4", "model": "Seagate ST1000DM003", "total": 916, "used": 845,
     "smart": {"status": "ok", "temp": 38, "hours": 41200, "realloc": 0, "pending": 0}, "source": "smartctl",
     "note": "Une partie de la médiathèque et des téléchargements"},
    {"id": "d2", "name": "/windocs", "mount": "/windocs", "fs": "ext4", "model": "Modèle non communiqué", "total": 916, "used": 916,
     "smart": {"status": "alert", "temp": 47, "hours": 61230, "realloc": 48, "pending": 3}, "source": "smartctl",
     "note": "Plein : sous la marge de 10 %"},
    {"id": "d3", "name": "/library", "mount": "/library", "fs": "ext4", "model": "TOSHIBA MG07ACA14TA", "total": 14000, "used": 1, "capacity": "14 To (12,7 Tio)", "label": "library",
     "smart": {"status": "ok", "temp": 31, "hours": 12, "realloc": 0, "pending": 0}, "source": "scrutiny", "note": "Formaté en ext4 (étiquette « library »), vide"},
]
CLIENT_OF_LIBRARY = "qBittorrent"  # the client the Torrents page shows


def _film_node(index, row):
    title, year, minutes, genre, _c, name, size, _u, seeding, disk, _d = row
    h = sha("old" + name)
    node = {"n": name, "d": 1, "age": 20 + index * 9, "film": title, "poster": index,
            "c": [{"n": name + ".mkv", "s": size, "age": 20 + index * 9, "hash": sha("file" + name), "film": title, "poster": index}]}
    if seeding:
        node["seed"] = {"client": CLIENT_OF_LIBRARY, "ratio": seeding[0], "hours": seeding[1], "hash": h}
        node["c"][0]["seed"] = node["seed"]
    return node


def storage_json():
    """Tree, disks, trash, organisation rows and settings for the Fichiers preview. Sizes in GB."""
    by_disk = {"d1": [], "d2": [], "d3": []}
    for index, row in enumerate(FILMS):
        by_disk["d2" if row[9][0] == "/windocs" else "d1"].append(_film_node(index, row))
    pulp = next(n for n in by_disk["d1"] if n["film"] == "Pulp Fiction")
    kung = next(n for n in by_disk["d1"] if n["film"] == "Kung Fu Jungle")
    ep = lambda n, s, age, seed=None: {"n": n, "s": s, "age": age, "hash": sha("ep" + n), **({"seed": seed} if seed else {})}
    bb_seed = {"client": "rTorrent", "ratio": 0.8, "hours": 70, "hash": sha("bb")}
    dune_seed = {"client": "qBittorrent", "ratio": 0.4, "hours": 20, "hash": sha("dune")}
    opp_seed = {"client": "Transmission", "ratio": 1.2, "hours": 150, "hash": sha("opp")}
    downloads = [
        {"n": "Dune.Part.Two.2024.MULTi.1080p.BluRay.x265-FRATERNiTY", "d": 1, "age": 2, "seed": dune_seed, "c": [
            {"n": "Dune.Part.Two.2024.MULTi.1080p.BluRay.x265-FRATERNiTY.mkv", "s": 14.2, "age": 2, "hash": sha("dune-mkv"), "seed": dune_seed},
            {"n": "Subs", "d": 1, "age": 2, "c": [{"n": "fr.srt", "s": 0.0001, "age": 2, "hash": sha("dune-srt")}]},
            {"n": "Dune.Part.Two.nfo", "s": 0.00001, "age": 2, "hash": sha("dune-nfo")}]},
        {"n": "Oppenheimer.2023.MULTi.2160p.UHD.BluRay.x265.HDR-ELiTE.mkv", "s": 19.0, "age": 5, "hash": sha("opp-mkv"), "seed": opp_seed},
        {"n": "Breaking.Bad.S01.MULTi.1080p.BluRay.x264-HDS", "d": 1, "age": 9, "seed": bb_seed, "c": [
            ep("Breaking.Bad.S01E01.MULTi.1080p.mkv", 2.1, 9, bb_seed), ep("Breaking.Bad.S01E02.MULTi.1080p.mkv", 2.0, 9, bb_seed),
            ep("Breaking.Bad.S01E03.MULTi.1080p.mkv", 2.2, 9, bb_seed)]},
        {"n": "the.office.us.s02e01.720p.webrip.x264.mkv", "s": 0.7, "age": 12, "hash": sha("office")},
        # A second copy of a film the library has: same bytes (same hash) for Kung Fu Jungle, other bytes for Pulp Fiction.
        {"n": kung["n"], "d": 1, "age": 4, "c": [dict(kung["c"][0], seed=None)]},
        {"n": pulp["n"], "d": 1, "age": 3, "c": [dict(pulp["c"][0], hash=sha("pulp-redownload"), s=2.5, seed=None)]},
        {"n": "sample.mkv", "s": 0.04, "age": 2, "hash": sha("sample")},
        {"n": "RARBG.txt", "s": 0.00001, "age": 30, "hash": sha("rarbg")},
    ]
    for node in downloads[4:6]:
        node.pop("seed", None)
        for child in node["c"]:
            child.pop("seed", None)
    office = {"n": "The Office (2005)", "d": 1, "age": 80, "c": [{"n": "Saison 01", "d": 1, "age": 80, "c": [
        {"n": f"The Office S01E0{i}.mkv", "s": 0.6, "age": 80, "hash": sha(f"office1{i}")} for i in range(1, 4)]}]}
    series = [
        {"n": "Severance (2022)", "d": 1, "age": 40, "c": [{"n": "Saison 01", "d": 1, "age": 40, "c": [
            {"n": f"Severance S01E0{i}.mkv", "s": 1.9, "age": 40, "hash": sha(f"sev{i}"),
             "seed": {"client": CLIENT_OF_LIBRARY, "ratio": 1.6, "hours": 300, "hash": sha("sev")}} for i in range(1, 4)]}]},
        office,
        {"n": "Dark (2017)", "d": 1, "age": 120, "c": [{"n": "Saison 01", "d": 1, "age": 120, "c": [
            {"n": f"Dark S01E0{i}.mkv", "s": 1.5, "age": 120, "hash": sha(f"dark{i}")} for i in range(1, 3)]}]},
    ]
    disks = []
    for d in DISKS:
        out = dict(d)
        films = [n for n in by_disk[d["id"]]]
        lib = sum(n["c"][0]["s"] for n in films)
        if d["id"] == "d1":
            lib += 2 * 0 + sum(c["s"] for s in series for ss in s["c"] for c in ss["c"])
        out["films"] = len(films)
        out["library"] = round(lib, 1)
        out["downloads"] = round(sum(_size(n) for n in downloads), 1) if d["id"] == "d1" else 0
        disks.append(out)
    roots = {
        "d1": [{"n": "Films", "d": 1, "age": 1, "lib": "Films", "c": by_disk["d1"]},
               {"n": "Séries", "d": 1, "age": 1, "lib": "Séries", "c": series},
               {"n": "Téléchargements", "d": 1, "age": 0, "dl": 1, "c": downloads}],
        "d2": [{"n": "Films", "d": 1, "age": 1, "lib": "Films", "c": by_disk["d2"]}],
        "d3": [{"n": "Films", "d": 1, "age": 0, "lib": "Films", "c": []},
               {"n": "Séries", "d": 1, "age": 0, "lib": "Séries", "c": []},
               {"n": "Téléchargements", "d": 1, "age": 0, "dl": 1, "c": []}],
    }
    trash = [
        {"id": "t1", "disk": "d1", "name": "Pulp.Fiction.1994.480p.DVDRip.x264-OLD.mkv", "from": "/saves/Films/Pulp.Fiction.1994.480p.DVDRip.x264-OLD",
         "by": "Vous", "ago": 1, "size": 1.2, "reason": "Remplacée par une meilleure version"},
        {"n": 0, "id": "t2", "disk": "d1", "name": "Dune.Part.One.2021.cam.mkv", "from": "/saves/Téléchargements/Dune.Part.One.2021.cam.mkv",
         "by": "Camille", "ago": 3, "size": 2.3, "reason": ""},
        {"id": "t3", "disk": "d1", "name": "Saison 02 (doublon)", "from": "/saves/Séries/Dark (2017)/Saison 02 (doublon)", "dir": 1,
         "by": "Vous", "ago": 5, "size": 9.8, "reason": ""},
        {"id": "t4", "disk": "d2", "name": "Old.Backups.2019.zip", "from": "/windocs/Old.Backups.2019.zip",
         "by": "Vous", "ago": 6, "size": 14.0, "reason": ""},
    ]
    tasks = [
        {"id": "h1", "kind": "move", "label": "Déplacer 1 élément", "who": "Camille", "ago_min": 95, "state": "done", "undo": True,
         "items": [{"name": "Ready.Player.One.2018.720p.WEB.x264-GRP", "from": "/saves/Téléchargements", "to": "/saves/Films",
                    "size": 2.2, "state": "done", "verified": True, "mode": "Même disque : déplacement instantané · client : qBittorrent (natif)"}]},
        {"id": "h2", "kind": "move", "label": "Déplacer 1 élément", "who": "Vous", "ago_min": 1500, "state": "failed", "undo": False,
         "items": [{"name": "Transformers.Age.of.Extinction.2014.1080p.BluRay.x264-GRP", "from": "/windocs/Films", "to": "/library/Films",
                    "size": 5.1, "state": "failed", "verified": False,
                    "reason": "Vérification échouée : 98,7 % des pièces valides après la copie. L'original est intact, le torrent a repris sur /windocs.",
                    "mode": "Autre disque : copie · client : qBittorrent (natif)"}]},
        {"id": "h3", "kind": "rename", "label": "Renommer 1 élément", "who": "Vous", "ago_min": 3000, "state": "done", "undo": True,
         "items": [{"name": "Dark.2017.S01.1080p.WEB → Dark (2017)", "from": "/saves/Séries", "to": "/saves/Séries",
                    "size": 3.0, "state": "done", "verified": True, "mode": "Renommage sur disque"}]},
    ]
    meta = lambda **k: k
    org = [
        # name in the library or downloads, kind, title, year, tmdb, res, codec, source, season/episode, seed
        meta(path="Films/The.Truman.Show.1998.720p.BluRay.x264-GRP", kind="film", title="The Truman Show", year=1998, tmdb=37165,
             res="720p", codec="x264", src="BluRay", lang="MULTi", ext="mkv", folder="Films", seed="qBittorrent", poster=0),
        meta(path="Films/Pulp.Fiction.1994.720p.WEB.x264-GRP", kind="film", title="Pulp Fiction", year=1994, tmdb=680,
             res="720p", codec="x264", src="WEB", lang="MULTi", ext="mkv", folder="Films", seed=None, poster=1),
        meta(path="Films/The.Lord.of.the.Rings.The.Return.of.the.King.2003.720p.BluRay.x264-GRP", kind="film",
             title="Le Seigneur des anneaux : Le Retour du roi", year=2003, tmdb=122, res="720p", codec="x264", src="BluRay", lang="MULTi",
             ext="mkv", folder="Films", seed="qBittorrent", poster=3),
        meta(path="Films/Ready.Player.One.2018.720p.WEB.x264-GRP", kind="film", title="Ready Player One", year=2018, tmdb=333339,
             res="720p", codec="x264", src="WEB", lang="MULTi", ext="mkv", folder="Films", seed="qBittorrent", poster=4),
        meta(path="Films/Kung.Fu.Jungle.2014.720p.BluRay.x264-GRP", kind="film", title="Kung Fu Jungle", year=2014, tmdb=296098,
             res="720p", codec="x264", src="BluRay", lang="MULTi", ext="mkv", folder="Films", seed=None, poster=5),
        meta(path="Téléchargements/Dune.Part.Two.2024.MULTi.1080p.BluRay.x265-FRATERNiTY", kind="film", title="Dune : Deuxième partie",
             year=2024, tmdb=693134, res="1080p", codec="x265", src="BluRay", lang="MULTi", ext="mkv", folder="Téléchargements",
             seed="qBittorrent", layout="Le torrent contient un dossier Subs/ et un .nfo à côté du film : le client ne peut pas les ranger dans un dossier de film propre.", poster=None),
        meta(path="Téléchargements/Oppenheimer.2023.MULTi.2160p.UHD.BluRay.x265.HDR-ELiTE.mkv", kind="film", title="Oppenheimer", year=2023,
             tmdb=872585, res="2160p", codec="x265", src="UHD BluRay", lang="MULTi", ext="mkv", folder="Téléchargements", seed="Transmission", poster=None),
        meta(path="Téléchargements/Breaking.Bad.S01.MULTi.1080p.BluRay.x264-HDS", kind="series", title="Breaking Bad", year=2008, tmdb=1396,
             res="1080p", codec="x264", src="BluRay", lang="MULTi", ext="mkv", folder="Téléchargements", seed="rTorrent", season=1, episodes=3, poster=None),
        meta(path="Téléchargements/the.office.us.s02e01.720p.webrip.x264.mkv", kind="series", title="The Office", year=2005, tmdb=2316,
             res="720p", codec="x264", src="WEB", lang="EN", ext="mkv", folder="Téléchargements", seed=None, season=2, episodes=1, poster=None),
    ]
    return {"disks": disks, "roots": roots, "trash": trash, "tasks": tasks, "org": org,
            "clients": [
                {"id": "qbittorrent", "name": "qBittorrent", "native": True},
                {"id": "transmission", "name": "Transmission", "native": True},
                {"id": "deluge", "name": "Deluge", "native": True},
                {"id": "rtorrent", "name": "rTorrent", "native": False},
                {"id": "utorrent", "name": "µTorrent", "native": False},
            ]}


def _size(node):
    return node.get("s", 0) + sum(_size(c) for c in node.get("c", []))
