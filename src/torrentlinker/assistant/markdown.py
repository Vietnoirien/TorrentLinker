"""Safe chat Markdown with bounded public image previews and original image links."""

from html import escape
from urllib.parse import quote, urlsplit

from markdown_it import MarkdownIt

from torrentlinker.assistant.images import image_url


def documentation_link(url: str) -> bool:
    from torrentlinker.documentation import guides

    parsed = urlsplit(url)
    return (
        not parsed.scheme
        and not parsed.netloc
        and not parsed.query
        and parsed.path
        in {
            "/documentation/" + guide["path"]
            for language in ("en", "fr")
            for guide in guides(language)
        }
    )


def render(text, *, proxy_images=True):
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    # CommonMark also accepts relative and mail links. Chat only opens HTTP(S).
    parser.validateLink = lambda url: (
        url.lower().startswith(("http://", "https://")) or documentation_link(url)
    )
    images = 0

    def image(tokens, index, options, env):
        nonlocal images
        token = tokens[index]
        url = token.attrGet("src") or ""
        label = escape(parser.renderer.renderInlineAsText(token.children or [], options, env))
        if not image_url(url):
            return label
        link = escape(url, quote=True)
        images += 1
        if images > 8:
            return f'<a href="{link}" rel="noopener noreferrer">{label or link}</a>'
        source = "api/assistant/image?url=" + quote(url, safe="") if proxy_images else url
        return (
            f'<a href="{link}" rel="noopener noreferrer">'
            f'<img src="{escape(source, quote=True)}" alt="{label}" '
            'loading="lazy" decoding="async" referrerpolicy="no-referrer" />'
            f"<br />{label or link}</a>"
        )

    parser.renderer.rules["image"] = image
    return parser.render(text)
