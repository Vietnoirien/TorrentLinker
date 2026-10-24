from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pytest

from torrentlinker.config import Settings
from torrentlinker.domain import ContentKind, LibraryFolder, Torrent
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.ebooks import (
    BookError,
    ComicBook,
    EpubBook,
    ReadingProgress,
    book_roots,
    discover_books,
    ebook_category,
    member_path,
    seeded_ebooks,
)
from torrentlinker.seeding import Seeding, SeedingRow
from torrentlinker.zen import ZenProfile, estimate


def ebook_view(count: int, root: Path = Path("/books")) -> Seeding:
    rows = [
        SeedingRow(Torrent(f"{i:040x}", f"Book {i}", root, state="stalledUP"), 1, 7020)
        for i in range(count)
    ]
    return Seeding(rows, estimate(ZenProfile(), []), [], {7020: IndexerCategory("Books", 7000)})


def make_epub(path: Path, *, chapters: int = 2) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/book.opf",
            "<package><metadata><title>A quiet library</title></metadata><manifest>"
            + "".join(
                f'<item id="c{i}" href="chapter{i}.xhtml" media-type="application/xhtml+xml"/>'
                for i in range(chapters)
            )
            + '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
            'properties="nav"/></manifest><spine>'
            + "".join(f'<itemref idref="c{i}"/>' for i in range(chapters))
            + "</spine></package>",
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            "<html><body><nav>"
            + "".join(f'<a href="chapter{i}.xhtml">Chapter {i + 1}</a>' for i in range(chapters))
            + "</nav></body></html>",
        )
        for i in range(chapters):
            archive.writestr(
                f"OEBPS/chapter{i}.xhtml",
                "<html><body>"
                + f"<h1>Chapter {i + 1}</h1><p>A room full of stories.</p>" * 60
                + "</body></html>",
            )
    return path


def test_unlock_counts_unique_seeding_ebooks_only():
    view = ebook_view(9999)
    assert seeded_ebooks(view) == 9999
    view.rows.append(view.rows[0])
    assert seeded_ebooks(view) == 9999
    torrent = Torrent("f" * 40, "Last book", Path("/books"), state="uploading")
    view.rows.append(SeedingRow(torrent, 1, 7020))
    assert seeded_ebooks(view) == 10000
    for state, progress, category in [
        ("pausedUP", 1, 7020),
        ("downloading", 0.5, 7020),
        ("stalledUP", 1, 2030),
    ]:
        view.rows[-1] = SeedingRow(replace(torrent, state=state, progress=progress), 1, category)
        assert seeded_ebooks(view) == 9999


def test_category_uses_ancestors_and_avoids_cycles():
    assert ebook_category(9001, {9001: IndexerCategory("Custom", 7000)})
    assert ebook_category(3030, {})
    assert not ebook_category(9001, {9001: IndexerCategory("Loop", 9001)})
    assert not ebook_category(None, {})


def test_roots_include_mapped_client_and_configured_local_folders(tmp_path):
    view = ebook_view(1, tmp_path / "mapped")
    settings = Settings(
        library_folders=[
            LibraryFolder(tmp_path / "books", kind=ContentKind.EBOOK),
            LibraryFolder(tmp_path / "movies", kind=ContentKind.MOVIE),
        ]
    )
    settings.download_folders = DownloadFolders({7000: str(tmp_path / "downloads")})
    assert set(book_roots(settings, view)) == {
        tmp_path / "mapped",
        tmp_path / "books",
        tmp_path / "downloads",
    }


def test_discovery_deduplicates_roots_and_ignores_incomplete_and_unreadable_formats(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    for name in ["a.EPUB", "b.pdf", "c.cbz", "d.cbr", "partial.epub.!qB", "video.mkv"]:
        (nested / name).write_bytes(b"fixture")
    found = discover_books([tmp_path, nested, tmp_path / "absent"])
    assert len(found.books) == 4
    assert found.unavailable == 1
    assert not discover_books([tmp_path], stop=lambda: True).books


def test_epub_reads_spine_and_human_chapter_titles_without_extracting(tmp_path):
    path = make_epub(tmp_path / "book.epub")
    before = path.read_bytes()
    book = EpubBook(path)
    assert book.title == "A quiet library"
    assert [c.title for c in book.chapters] == ["Chapter 1", "Chapter 2"]
    assert b"Chapter 2" in book.read(book.chapters[1].name)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "href",
    ["../../secret", "file:///secret", "https://example.org/pixel", "//host/file", "%2fetc/passwd"],
)
def test_epub_resources_reject_external_or_escaping_paths(href):
    with pytest.raises(BookError):
        member_path("OEBPS/chapter.xhtml", href)


def test_epub_fragment_and_parent_resources_resolve_inside_archive():
    assert member_path("OEBPS/chapter.xhtml", "#heading") == "OEBPS/chapter.xhtml"
    assert member_path("OEBPS/chapter.xhtml", "../images/pic.png") == "images/pic.png"


def test_comic_pages_have_natural_order_and_only_images(tmp_path):
    path = tmp_path / "comic.cbz"
    with ZipFile(path, "w") as archive:
        for name in ["page10.png", "page2.png", "page1.png", "notes.txt"]:
            archive.writestr(name, b"fixture")
    comic = ComicBook(path)
    assert comic.pages == ["page1.png", "page2.png", "page10.png"]
    assert comic.read("page2.png") == b"fixture"


def test_missing_cbr_tool_has_actionable_error(tmp_path, monkeypatch):
    path = tmp_path / "comic.cbr"
    path.write_bytes(b"Rar!")
    monkeypatch.setattr("torrentlinker.ebooks.archives._tool", lambda name: None)
    with pytest.raises(BookError, match="7-Zip or unrar"):
        ComicBook(path)


def test_progress_survives_restarts_without_modifying_book(tmp_path):
    book = tmp_path / "book.epub"
    book.write_bytes(b"book")
    progress = ReadingProgress(tmp_path / "app" / "progress.json")
    progress.save(book, 3, 0.7)
    assert ReadingProgress(progress.path).get(book) == (3, 0.7)
    assert book.read_bytes() == b"book"


def test_cbr_prefers_unrar_and_reads_a_page_without_extracting_to_library(tmp_path, monkeypatch):
    import subprocess

    path = tmp_path / "comic.cbr"
    path.write_bytes(b"Rar!")
    monkeypatch.setattr("torrentlinker.ebooks.archives._tool", lambda name: "/tools/" + name)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 20
        assert kwargs["stdin"] == subprocess.DEVNULL
        if args[1] == "lt":
            return subprocess.CompletedProcess(args, 0, "Name: page1.png\nType: File\nSize: 3\n\n")
        kwargs["stdout"].write(b"png")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("torrentlinker.ebooks.subprocess.run", run)
    book = ComicBook(path)
    assert book.read("page1.png") == b"png"
    assert all(args[0] == "/tools/unrar" for args in calls)
    assert list(tmp_path.iterdir()) == [path]


def test_epub_external_toc_link_does_not_block_local_chapters(tmp_path):
    path = make_epub(tmp_path / "local.epub")
    with ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["OEBPS/nav.xhtml"] = (
        b'<html><body><nav><a href="https://example.invalid">Publisher</a>'
        b'<a href="chapter0.xhtml">Start</a></nav></body></html>'
    )
    with ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    book = EpubBook(path)
    assert len(book.chapters) == 2
    assert book.chapters[0].title == "Start"


def test_book_categories_use_file_and_pack_paths_without_classifying_shared_folder(tmp_path):
    from torrentlinker.ebooks import book_categories

    view = ebook_view(0)
    view.categories[7010] = IndexerCategory("Comics", 7000)
    view.categories[7020] = IndexerCategory("Books", 7000)
    (tmp_path / "pack").mkdir()
    for file in ("renamed.epub", "pack/book.pdf", "unknown.pdf"):
        (tmp_path / file).touch()
    view.rows.extend(
        [
            SeedingRow(Torrent("a", "Release name", tmp_path, files={"renamed.epub": 1}), 1, 7010),
            SeedingRow(Torrent("b", "pack", tmp_path), 1, 7020),
        ]
    )
    hints = book_categories(Settings(), view)
    library = discover_books((tmp_path,), categories=hints)
    by_name = {book.path.name: book.category for book in library.books}
    assert by_name["renamed.epub"][-1] == "Comics"
    assert by_name["book.pdf"][-1] == "Books"
    assert by_name["unknown.pdf"] == ()
