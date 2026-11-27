"""Example data for the Tracker Series preview: library series, ~18 tracker series, posters.

The Library series are written into the real media store (so the real Séries tab draws them);
the Tracker Series are plain data the preview script serves in place of the tracker-films
routes. Nothing is fetched: posters are drawn here.
"""

import hashlib
import io
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from torrentlinker.domain import LibraryFolder

GB = 1000**3
DAY = 86400

# Titles (fr), original, year, kind, genres, age rating, airing?, colours, synopsis,
# seasons [(episodes, state)], library seasons, intégrale ("covers" list or None).
# state: "pack" (a full pack), ("eps", k) (only k episodes on the tracker), "integ" (only in the Intégrale)
SERIES = [
    ("tv-136315", "The Bear", "The Bear", 2022, "tv", ["Drame", "Comédie"], "16", True, ("#7a2e1b", "#e8a35a"),
     "Carmy, jeune chef étoilé, rentre à Chicago reprendre le sandwich shop familial après la mort de son frère. Entre dettes, brigade en ébullition et fantômes du passé, il tente de faire de la cuisine un refuge.",
     [(8, "pack"), (10, "pack"), (10, "pack"), (10, ("eps", 6))], [1, 2], None),
    ("tv-70523", "Dark", "Dark", 2017, "tv", ["Science-Fiction", "Mystère"], "16", False, ("#1d2a4a", "#9aa7c7"),
     "À Winden, la disparition d'un enfant fait remonter quatre familles à leurs secrets et ouvre une faille dans le temps : le passé, le présent et l'avenir s'y répondent.",
     [(10, "pack"), (8, "pack"), (8, "pack")], [1, 2, 3], ["S01", "S02", "S03"]),
    ("tv-87108", "Chernobyl", "Chernobyl", 2019, "tv", ["Drame", "Histoire"], "16", False, ("#26402a", "#8bb08d"),
     "Avril 1986. Au lendemain de l'explosion du réacteur, ceux qui ont affronté la catastrophe racontent ce que l'Union soviétique a voulu taire.",
     [(5, "pack")], [1], None),
    ("tv-95396", "Severance", "Severance", 2022, "tv", ["Science-Fiction", "Thriller"], "16", False, ("#2c5f7a", "#8fb4c9"),
     "Chez Lumon, des employés ont accepté de séparer chirurgicalement leur mémoire du travail et celle de la vie privée. Mark découvre ce que son autre lui sait déjà.",
     [(9, "pack"), (10, "pack")], [], [1, 2]),
    ("tv-1396", "Breaking Bad", "Breaking Bad", 2008, "tv", ["Drame", "Crime"], "16", False, ("#3d5a1f", "#d4c34a"),
     "Walter White, professeur de chimie atteint d'un cancer, se met à fabriquer de la méthamphétamine pour mettre sa famille à l'abri du besoin.",
     [(7, "pack"), (13, "pack"), (13, "pack"), (13, "integ"), (16, "integ")], [], [1, 2, 3, 4, 5]),
    ("tv-71712", "Les Revenants", "Les Revenants", 2012, "tv", ["Drame", "Fantastique"], "12", False, ("#3b3b45", "#b7b2a5"),
     "Dans une petite ville de montagne, des morts reviennent comme si rien ne s'était passé. Les vivants n'ont pas fini de les attendre.",
     [(8, "pack"), (8, "pack")], [], None),
    ("tv-97546", "Squid Game", "오징어 게임", 2021, "tv", ["Thriller", "Drame"], "18", False, ("#8a1f3a", "#f0a0b0"),
     "Des joueurs endettés acceptent une invitation : des jeux d'enfants, des enjeux mortels et une cagnotte colossale.",
     [(9, "pack"), (7, "pack"), (6, "pack")], [], None),
    ("tv-100088", "The Last of Us", "The Last of Us", 2023, "tv", ["Drame", "Aventure"], "16", True, ("#18323a", "#6fb3a5"),
     "Vingt ans après l'effondrement de la civilisation, Joel doit escorter Ellie, quatorze ans, à travers des États-Unis ravagés.",
     [(9, "pack"), (7, ("eps", 5))], [], None),
    ("tv-70", "Peaky Blinders", "Peaky Blinders", 2013, "tv", ["Crime", "Drame"], "16", False, ("#3a2a1f", "#c9a46b"),
     "Birmingham, 1919. Tommy Shelby mène sa famille de la pègre locale vers les cercles du pouvoir.",
     [(6, "pack"), (6, "pack"), (6, "integ"), (6, "integ"), (6, "integ"), (6, "integ")], [], [3, 4, 5, 6, 1, 2]),
    ("tv-72750", "Baron noir", "Baron noir", 2016, "tv", ["Drame", "Politique"], "12", False, ("#2d4f5e", "#e5c07b"),
     "Philippe Rickwaert, député-maire du Nord, plonge dans les coulisses de la conquête du pouvoir.",
     [(8, "pack"), (8, "pack"), (8, "pack")], [], None),
    ("tv-67744", "Le Bureau des légendes", "Le Bureau des légendes", 2015, "tv", ["Espionnage", "Drame"], "12", False, ("#2a3b4d", "#9fb3c8"),
     "Au sein de la DGSE, des agents clandestins vivent sous une fausse identité pendant des années. Revenir est l'épreuve.",
     [(10, "pack"), (10, "pack"), (10, "pack"), (10, "pack"), (10, "pack")], [], None),
    ("tv-85552", "Notre planète", "Our Planet", 2019, "doc", ["Documentaire", "Nature"], "TP", False, ("#1f6b4a", "#a8d8b9"),
     "Du Grand Nord aux récifs, un tour du monde du vivant et de ce qui le menace, aux côtés de ceux qui le protègent.",
     [(8, "pack"), (4, ("eps", 2))], [], None),
    ("tv-1432", "Cosmos : Une odyssée à travers l'univers", "Cosmos: A Spacetime Odyssey", 2014, "doc", ["Documentaire", "Science"], "TP", False, ("#3a1f6b", "#e46bd0"),
     "Un voyage dans l'espace et le temps, des premières cellules aux confins de l'univers observable.",
     [(13, "pack")], [], None),
    ("tv-76479", "The Boys", "The Boys", 2019, "tv", ["Action", "Comédie"], "18", True, ("#8a3a1f", "#ffd166"),
     "Dans un monde où les super-héros sont des célébrités corrompues, une bande de justiciers veut les faire tomber.",
     [(8, "pack"), (8, "pack"), (8, "pack"), (8, "pack"), (8, ("eps", 3))], [], None),
    ("an-1429", "L'Attaque des Titans", "進撃の巨人", 2013, "anime", ["Animation", "Action", "Fantastique"], "16", False, ("#4b2a14", "#d98e3f"),
     "L'humanité vit retranchée derrière de hauts murs, à l'abri de géants mangeurs d'hommes. Eren jure d'exterminer jusqu'au dernier.",
     [(25, "integ"), (12, "integ"), (22, "integ"), (30, "integ")], [], [1, 2, 3, 4]),
    ("an-209867", "Frieren", "葬送のフリーレン", 2023, "anime", ["Animation", "Fantastique", "Aventure"], "10", True, ("#4a3b6b", "#c9b8e8"),
     "Après la défaite du roi démon, l'elfe Frieren, qui vit mille ans, découvre ce que les humains ont laissé derrière eux.",
     [(28, ("eps", 18))], [], None),
    ("an-85937", "Demon Slayer", "鬼滅の刃", 2019, "anime", ["Animation", "Action"], "12", False, ("#8a1f1f", "#f1c232"),
     "Tanjiro devient pourfendeur de démons pour sauver sa sœur Nezuko, transformée en démon.",
     [(26, "pack"), (7, "pack"), (11, "pack"), (11, "pack")], [], None),
]

KINDS = {"tv": "Série TV", "doc": "Série documentaire", "anime": "Animation série"}

# What a title and its synopsis look like, per episode. Rotated by series, so two shows do not share a list.
BEATS = [
    ("Le retour", "Un visage du passé frappe à la porte et rouvre ce que tout le monde croyait réglé."),
    ("Nuit blanche", "Une longue nuit met chacun face à ce qu'il cache depuis des semaines."),
    ("Les fondations", "On revient sur ce qui tient encore debout, et sur ce qui va céder en premier."),
    ("Mauvaise nouvelle", "Une annonce inattendue bouscule les plans et fait naître les premiers soupçons."),
    ("Le prix à payer", "Une décision prise trop vite coûte plus cher que prévu."),
    ("Un secret de famille", "Un vieux dossier ressort et change la façon dont tous se regardent."),
    ("La tempête", "Tout s'enchaîne : les alliances se défont, les vérités sortent."),
    ("Ligne rouge", "Quelqu'un franchit ce qu'il s'était juré de ne jamais faire."),
    ("Cartes sur table", "Une explication longtemps repoussée a enfin lieu."),
    ("Les cendres", "Il faut déblayer ce qui reste avant de reconstruire quoi que ce soit."),
    ("Double jeu", "Chacun joue sa partie, et l'un d'eux joue contre tous."),
    ("Le dernier mot", "Tout se joue sur une conversation que personne ne voulait avoir."),
    ("À contretemps", "Un détail décalé révèle que rien n'est tout à fait comme on le croyait."),
    ("Sans filet", "Plus de plan de secours : il faut avancer avec ce qu'on a."),
    ("Retour de flamme", "Ce qu'on avait enterré revient, plus fort et mieux informé."),
    ("Les héritiers", "La relève prend la parole, et personne n'est prêt à l'entendre."),
]


def sha(text):
    return hashlib.sha1(text.encode()).hexdigest()


def dots(title):
    return "".join(c if c.isalnum() else "." for c in title.replace(" : ", ".").replace("'", ".")).replace("..", ".").strip(".")


def episodes(index, number, count, tracker_count):
    """Episode titles and synopses of one season; `tracker_count` of them exist on the tracker."""
    out = []
    for e in range(1, count + 1):
        title, text = BEATS[(index * 5 + number * 3 + e) % len(BEATS)]
        out.append({"n": e, "title": title, "synopsis": text, "tracker": e <= tracker_count})
    return out


def release(name, size, seeders, tracker, score):
    color = "green" if score >= 80 else "yellow" if score >= 60 else "red"
    return {"hash": sha(name), "name": name, "size": int(size * GB), "seeders": seeders, "tracker": tracker,
            "score": score, "color": color}


def build():
    """The Tracker Series, as the preview serves them (see series.js)."""
    out, now = [], time.time()
    for index, (sid, title, original, year, kind, genres, rating, airing, colours, synopsis, seasons, owned, integ) in enumerate(SERIES):
        base = dots(original if kind != "doc" else title)
        row = {"id": sid, "title": title, "original": original, "year": year, "kind": kind, "genres": genres,
               "rating": rating, "airing": airing, "colours": colours, "synopsis": synopsis, "owned": owned,
               "published": now - (index * 2 + 1) * DAY, "seeders": 80 - index * 4, "seasons": [], "integrale": None}
        for n, (count, state) in enumerate(seasons, 1):
            tracker_count = count if state in ("pack", "integ") else state[1]
            season = {"n": n, "count": count, "state": "pack" if state == "pack" else "integ" if state == "integ" else "episodes",
                      "episodes": episodes(index, n, count, tracker_count), "releases": []}
            per = count * (0.45 if kind == "anime" else 1.4)
            if state == "pack":
                season["releases"] = [
                    release(f"{base}.S{n:02d}.MULTi.1080p.WEB.x265-FRATERNiTY", per, 60 - n * 3 + index, "c411", 88 - n),
                    release(f"{base}.S{n:02d}.FRENCH.720p.WEB.x264-MTV", per * 0.55, 22 + index, "tr4ker", 71),
                ]
            elif state != "integ":
                season["releases"] = [
                    release(f"{base}.S{n:02d}E{e:02d}.MULTi.1080p.WEB.x265-FRATERNiTY", 1.4 if kind != "anime" else 0.45, 30 - e, "c411", 84)
                    for e in range(1, state[1] + 1)
                ]
            row["seasons"].append(season)
        if integ:
            covered = sorted(integ if isinstance(integ[0], int) else [int(s[1:]) for s in integ])
            row["integrale"] = {
                "seasons": covered, "release": release(f"{base}.INTEGRALE.S01-S{max(covered):02d}.MULTi.1080p.BluRay.x265-HDS",
                sum(row["seasons"][s - 1]["count"] for s in covered) * (0.5 if kind == "anime" else 1.3), 54 + index, "c411", 91),
            }
        out.append(row)
    return out


# ---- the Library: real series in the real media store ------------------------------------

LIBRARY = ["tv-136315", "tv-70523", "tv-87108"]  # The Bear (seasons 1-2 of 4), Dark, Chernobyl: complete ones hide from Members


def poster(title, colours, small=False):
    """A gradient poster with the title: no outside image."""
    width, height = (400, 600) if small else (600, 900)
    top, bottom = (tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in colours)
    picture = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(picture)
    for y in range(height):
        mix = y / height
        draw.line([(0, y), (width, y)], fill=tuple(int(a + (b - a) * mix) for a, b in zip(top, bottom)))
    font = None
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(path, 44 if small else 62)
            break
        except OSError:
            pass
    font = font or ImageFont.load_default()
    lines, line = [], ""
    for word in title.split():
        if len(line + " " + word) > (12 if small else 13) and line:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    lines.append(line)
    step = 54 if small else 78
    y = height // 2 - step // 2 * len(lines)
    for text in lines:
        w = draw.textlength(text, font=font)
        draw.text(((width - w) / 2 + 3, y + 3), text, fill=(0, 0, 0), font=font)
        draw.text(((width - w) / 2, y), text, fill=(255, 255, 255), font=font)
        y += step
    out = io.BytesIO()
    picture.save(out, "PNG")
    return out.getvalue()


def by_id():
    return {row["id"]: row for row in build()}


def seed(app, setup, root: Path):
    """Write the Library series (files, then metadata) into the real media store."""
    media = app.state.assistant.agent.media
    shows = root / "Séries"
    shows.mkdir()
    data = by_id()
    for sid in LIBRARY:
        row = data[sid]
        owned = row["owned"] or [s["n"] for s in row["seasons"]]
        for season in row["seasons"]:
            if season["n"] not in owned:
                continue
            folder = shows / f"{row['title']} ({row['year']})" / f"Saison {season['n']:02d}"
            folder.mkdir(parents=True)
            for ep in season["episodes"]:
                name = f"{dots(row['original'])}.S{season['n']:02d}E{ep['n']:02d}.MULTi.1080p.WEB.x265-GRP.mkv"
                with (folder / name).open("wb") as video:
                    video.truncate(int(1.3 * GB))
    setup.settings.library_folders = [LibraryFolder(shows)]
    setup.save()
    with (
        patch.object(type(media), "enrich", lambda *a, **k: "ok"),
        patch.object(type(media), "tracker_refresh", lambda *a, **k: "complete"),
        patch.object(type(media), "films_refresh", lambda *a, **k: None),
    ):
        media.scan("default", threading.Event(), lambda _p: None)
    now = time.time()
    with media.lock, media.db:
        rows = media.db.execute("SELECT id, path, body FROM media_items").fetchall()
        art = {}
        for sid in LIBRARY:
            art[sid] = media.cache_artwork(poster(data[sid]["title"], data[sid]["colours"]))
        for i, db in enumerate(rows):
            body = json.loads(db["body"])
            path = Path(db["path"])
            season_number = int(path.parent.name.split()[-1])
            episode_number = int(path.stem.split("E")[1][:2])
            row = next(r for r in (data[s] for s in LIBRARY) if path.parts[-3].startswith(r["title"]))
            ep = row["seasons"][season_number - 1]["episodes"][episode_number - 1]
            body |= {
                "title": row["title"], "series": row["title"], "season": season_number, "episode": episode_number,
                "episode_title": ep["title"], "year": str(row["year"]), "genre": ", ".join(row["genres"]),
                "description": row["synopsis"], "duration": 3000 + 120 * (i % 9), "language": "MULTI",
                "rating": round(7.5 + (i % 17) / 10, 1), "artwork": art[row["id"]],
                "age_rating": {"rating": row["rating"], "source": "tmdb", "by": "", "suggestion": None},
            }
            media.db.execute("UPDATE media_items SET body=?, size=?, added=? WHERE id=?",
                             (json.dumps(body), int(1.3 * GB), now - i * 1800, db["id"]))
        first = {}
        for db in media.db.execute("SELECT id, body FROM media_items").fetchall():
            first.setdefault(json.loads(db["body"])["series"], db["id"])
    for name, item in first.items():  # the Age Rating is a person's, kept per series
        media.rate("default", item, next(r["rating"] for r in data.values() if r["title"] == name), setter="owner", name="Viet")
    with media.lock, media.db:
        media.db.execute("INSERT OR REPLACE INTO media_options VALUES (?,?)", ("tracker-status:default", json.dumps("complete")))
        media.db.execute("INSERT OR REPLACE INTO media_options VALUES (?,?)", ("tracker-run:default", json.dumps(now + 10**7)))
