"""Render the BBCode of a c411 description as HTML, close enough to preview it."""

from __future__ import annotations

import html
import re

_SIMPLE = {
    "b": ("<b>", "</b>"),
    "i": ("<i>", "</i>"),
    "u": ("<u>", "</u>"),
    "s": ("<s>", "</s>"),
    "center": ('<div align="center">', "</div>"),
    "h1": ("<h1>", "</h1>"),
    "h2": ("<h2>", "</h2>"),
    "h3": ("<h3>", "</h3>"),
    "h4": ("<h4>", "</h4>"),
    "code": ("<pre>", "</pre>"),
    "quote": ("<blockquote>", "</blockquote>"),
}
_SAFE_URL = re.compile(r"^https?://[^\s\"'<>]+$")


def bbcode_to_html(text: str) -> str:
    """HTML for `text`; anything that is not a known tag stays as written, escaped."""
    out = html.escape(text, quote=False)
    for tag, (start, end) in _SIMPLE.items():
        out = re.sub(rf"\[{tag}\]", start, out, flags=re.IGNORECASE)
        out = re.sub(rf"\[/{tag}\]", end, out, flags=re.IGNORECASE)
    out = re.sub(r"\[img\](.*?)\[/img\]", _image, out, flags=re.IGNORECASE | re.DOTALL)
    out = re.sub(r"\[url=([^\]]+)\](.*?)\[/url\]", _link, out, flags=re.IGNORECASE | re.DOTALL)
    out = re.sub(r"\[url\](.*?)\[/url\]", lambda m: _link(m, m.group(1)), out, flags=re.I)
    out = re.sub(r"\[size=\d+\]|\[/size\]|\[color=[^\]]+\]|\[/color\]", "", out, flags=re.I)
    out = re.sub(
        r"\[spoiler(?:=([^\]]*))?\]",
        lambda m: f"<p><b>▸ {m.group(1) or 'Spoiler'}</b></p><div>",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\[/spoiler\]", "</div>", out, flags=re.IGNORECASE)
    out = re.sub(r"\[list=1\]", "<ol>", out, flags=re.IGNORECASE)
    out = re.sub(r"\[list\]", "<ul>", out, flags=re.IGNORECASE)
    out = re.sub(r"\[/list\]", "</ul>", out, flags=re.IGNORECASE)
    out = re.sub(r"\[\*\]([^\n\[]*)", r"<li>\1</li>", out)
    return out.replace("\n", "<br>")


def _image(m: re.Match[str]) -> str:
    url = html.unescape(m.group(1).strip())
    if not _SAFE_URL.match(url):
        return m.group(0)
    return f'<img src="{html.escape(url)}" width="300">'


def _link(m: re.Match[str], label: str | None = None) -> str:
    url = html.unescape(m.group(1).strip())
    if not _SAFE_URL.match(url):
        return m.group(0)
    return f'<a href="{html.escape(url)}">{label if label is not None else m.group(2)}</a>'
