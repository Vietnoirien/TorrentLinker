"""Safe chat Markdown: tables and formatting, without HTML or embedded resources."""

from markdown_it import MarkdownIt


def render(text):
    parser = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")
    # CommonMark also accepts relative and mail links. Chat only opens HTTP(S).
    parser.validateLink = lambda url: url.lower().startswith(("http://", "https://"))
    return parser.render(text)
