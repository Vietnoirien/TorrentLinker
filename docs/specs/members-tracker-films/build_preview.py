"""Build the tracker-films preview as one self-contained file: members-tracker-films-preview.html.

The page is the Médias panel itself (`src/torrentlinker/web/static/media/view.html`, its CSS
and scripts, inlined verbatim). Only the host transport is replaced (preview-stub.js, which
answers from fixtures.js) and the spec's additions are layered on top (preview.js and
preview.css). Run again after the panel changes:

    python3 docs/specs/members-tracker-films/build_preview.py
"""

import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
MEDIA = HERE.parents[2] / "src" / "torrentlinker" / "web" / "static" / "media"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


page = read(MEDIA / "view.html")


def style(match: re.Match) -> str:
    name = match.group(1)
    return f'<style data-source="{name}">\n{read((MEDIA / name).resolve())}\n</style>'


def script(match: re.Match) -> str:
    name = match.group(1)
    if name == "../panel/transport.js":
        # The stub supplies TLPanel.connect; the fixtures come first.
        return (
            f'<script data-source="fixtures.js">\n{read(HERE / "fixtures.js")}\n</script>'
            f'<script data-source="preview-stub.js">\n{read(HERE / "preview-stub.js")}\n</script>'
        )
    return f'<script data-source="{name}">\n{read((MEDIA / name).resolve()).replace("</script", "<\\/script")}\n</script>'


page = re.sub(r'<link rel="stylesheet" href="([^"]+)">', style, page)
page = re.sub(r'<script src="([^"]+)"></script>', script, page)
page = page.replace("<title>Media</title>", "<title>Sur le tracker · aperçu</title>", 1)
page = page.replace('<html lang="en">', '<html lang="fr" data-theme="dark">', 1)
page = page.replace("</head>", f'<style data-source="preview.css">\n{read(HERE / "preview.css")}\n</style></head>', 1)
# Two variants of the genre grid's control: A, a row of chips; B, a small "Sur le tracker · Genre ▾" line.
for variant, name in (("chips", "members-tracker-films-preview.html"), ("menu", "members-tracker-films-preview-genre-menu.html")):
    built = page.replace(
        "</body>",
        f'<script>const PREVIEW_VARIANT = "{variant}";</script>'
        f'<script data-source="preview.js">\n{read(HERE / "preview.js")}\n</script></body>',
        1,
    )
    out = HERE / name
    out.write_text(built, encoding="utf-8")
    print(out, f"{out.stat().st_size / 1e6:.1f} MB")
