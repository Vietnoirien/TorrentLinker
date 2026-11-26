"""Tracker Films in an actual browser: the landing's genre rows, one genre's grid, the pinned
film panel for a Member and for the Owner. The index is seeded; no tracker or TMDb is read."""

import os
import socket
import threading
import time

import pytest

from tests.film_support import seed_index
from tests.test_web_plan_execution import prepared
from torrentlinker.web.app import create_app

pytestmark = pytest.mark.skipif(os.getenv("TL_WEB_BROWSER") != "1", reason="opt-in browser test")

FILMS = {
    "1": ("Dune", "Dune", "2021", ["Science-Fiction", "Aventure"], "12", 155),
    "2": ("Alien", "Alien", "1979", ["Horreur", "Science-Fiction"], "16", 117),
    "3": ("Blade Runner", "Blade Runner", "1982", ["Science-Fiction", "Drame"], "12", 117),
    "4": ("Chihiro", "Spirited Away", "2001", ["Animation", "Familial"], "TP", 125),
}
GB = 10**9
RELEASES = [
    ("c411", "a" * 40, "Dune.2021.MULTi.1080p.WEB.x264-TEAM", 4 * GB, 30, "1"),
    ("tr4ker", "b" * 40, "Dune.2021.MULTi.2160p.BluRay.x265-TEAM", 40 * GB, 5, "1"),
    ("c411", "c" * 40, "Alien.1979.MULTi.1080p.BluRay.x264-TEAM", 7 * GB, 2, "2"),
    ("c411", "d" * 40, "Blade.Runner.1982.MULTi.1080p.BluRay.x264-TEAM", 6 * GB, 9, "3"),
    ("c411", "e" * 40, "Chihiro.2001.MULTi.1080p.BluRay.x264-TEAM", 8 * GB, 20, "4"),
]


def test_a_member_browses_the_tracker_films_by_genre_and_asks_and_the_owner_sees_releases(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Caps, Permission

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    lea = app.state.accounts.create(
        "Léa", "lea", {Permission.FILMS, Permission.REQUEST}, password="lea-password-long"
    )
    app.state.accounts.set_caps(lea, Caps(requests_per_week=3, bytes_per_week=100 * GB))
    seed_index(app.state.agent_service.media, FILMS, RELEASES, poster=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            base = f"http://127.0.0.1:{listener.getsockname()[1]}/"
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                page.get_by_label("Sign-in name").fill("lea")
                page.get_by_label("Password", exact=True).fill("lea-password-long")
                page.locator("#login-form button.primary").click()
                page.wait_for_url("**#/media/video")
                page.goto(base + "#/media/video/tracker")
                frame = page.frame_locator("#media-frame")
                head = frame.locator(".films-landing")
                expect(head.get_by_role("heading", name="On the tracker")).to_be_visible(
                    timeout=15000
                )
                # Rows: new and most shared have no "See all"; a genre's row has one.
                new = frame.locator('section[aria-label="New on the tracker"]')
                expect(new).to_be_visible()
                assert new.get_by_role("button", name="See all").count() == 0
                scifi = frame.locator('section[aria-label="Science-Fiction"]')
                expect(scifi.locator(".media-row-card")).to_have_count(3)
                # Choosing a film fills the pinned banner with its synopsis, never a release.
                scifi.locator(".media-row-card", has_text="Dune").click()
                feature = frame.locator("#media-feature")
                expect(feature.get_by_text("Synopsis de Dune.")).to_be_visible()
                expect(feature.get_by_text("TEAM")).to_have_count(0)
                expect(feature.get_by_text("You have 3 Requests")).to_be_visible()
                page.screenshot(path=str(tmp_path / "landing-member.png"))
                # "See all" opens that genre's grid, with its line and a way to narrow it.
                scifi.get_by_role("button", name="See all").click()
                bar = frame.locator(".films-bar")
                expect(bar.locator(".films-genre")).to_have_value("Science-Fiction")
                expect(frame.locator("#media-results .media-card")).to_have_count(3)
                bar.locator(".films-narrow").select_option("Aventure")
                expect(frame.locator("#media-results .media-card")).to_have_count(1)
                expect(frame.locator("#media-results .media-card h3")).to_have_text("Dune")
                page.screenshot(path=str(tmp_path / "grid-member.png"))
                frame.locator("#media-results").get_by_role("button", name="View").click()
                feature.get_by_role("button", name="Ask the owner").click()
                expect(feature.get_by_text("Pending", exact=True)).to_be_visible()
                [asked] = app.state.requests.mine(lea)
                assert asked["film"] == "tmdb-1" and asked["infohash"] == ""
                assert asked["size"] == 4 * GB  # the pre-selected release, never chosen by her
                # "‹ Genres" returns to the landing.
                bar.get_by_role("button", name="‹ Genres").click()
                expect(head.get_by_role("heading", name="On the tracker")).to_be_visible()
                # The Member's own page opens that same landing.
                page.goto(base + "#/media/video")
                page.evaluate("navigate('member-search')")
                expect(head.get_by_role("heading", name="On the tracker")).to_be_visible()

                # The Owner sees the pre-selection, the releases and the correction.
                page.goto(base)
                page.evaluate(
                    "fetch('api/logout', {method: 'POST', headers: {'X-TorrentLinker': '1'}})"
                )
                page.reload()
                page.get_by_role("button", name="I am the owner").click()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                page.goto(base + "#/media/video/tracker")
                owner = frame.locator('section[aria-label="Science-Fiction"]')
                owner.locator(".media-row-card", has_text="Dune").click(timeout=15000)
                expect(feature.get_by_text("Pre-selected", exact=True)).to_be_visible()
                expect(feature.get_by_role("button", name="Fix the film")).to_be_visible()
                feature.get_by_role("button", name="Releases (2)").click()
                dialog = frame.locator("#media-details")
                expect(dialog.locator(".films-release")).to_have_count(2)
                expect(dialog.get_by_text("Dune.2021.MULTi.2160p.BluRay.x265-TEAM")).to_be_visible()
                page.screenshot(path=str(tmp_path / "releases-owner.png"))
                assert not errors
                print(tmp_path)
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_the_holder_answers_a_household_ask_from_the_bell(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from torrentlinker.accounts import Permission
    from torrentlinker.member_requests import FilmAsk

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    accounts = app.state.accounts
    lea = accounts.create(
        "Léa", "lea", {Permission.FILMS, Permission.REQUEST}, password="lea-password-long"
    )
    accounts.set_pin(lea, "", "2468")
    tom = accounts.add_viewer(lea, "Tom", {Permission.FILMS}, None, True)
    seed_index(app.state.agent_service.media, FILMS, RELEASES, poster=False)
    app.state.household_asks.ask(lea, tom, "", FilmAsk("tmdb-1", "Dune", "2021", 4 * GB))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{listener.getsockname()[1]}/")
                page.get_by_label("Sign-in name").fill("lea")
                page.get_by_label("Password", exact=True).fill("lea-password-long")
                page.locator("#login-form button.primary").click()
                page.wait_for_url("**#/media/video")
                frame = page.frame_locator("#media-frame")
                expect(frame.locator("#media-requests-bell b")).to_have_text("1", timeout=15000)
                frame.locator("#media-requests-bell").click()
                drawer = frame.locator("#media-requests")
                expect(drawer.get_by_text("My household's asks")).to_be_visible()
                expect(drawer.get_by_text("Tom")).to_be_visible()
                drawer.get_by_role("button", name="Accept").click()
                expect(drawer.get_by_text("accepted, asked of the owner")).to_be_visible()
                [request] = app.state.requests.mine(lea)
                assert request["film"] == "tmdb-1" and request["state"] == "pending"
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)


def test_a_film_identified_while_the_owner_looks_swaps_in_place_without_moving_the_page(tmp_path):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config,
        members_enabled=True,
        password="test-password-long",
        service_override=setup,
        monitor_verifications=False,
    )
    media = app.state.agent_service.media
    films = {
        **FILMS,
        "5": ("Autre", "Other", "2010", ["Drame"], "12", 100),
        "9": ("Mystère", "Mystery", "2012", ["Drame"], "12", 100),
    }
    releases = [
        *RELEASES,
        ("c411", "5" * 40, "Autre.2010.MULTi.1080p.WEB.x264-TEAM", 3 * GB, 4, "5"),
        ("c411", "f" * 40, "Mystery.Film.2012.MULTi.1080p.WEB.x264-TEAM", 3 * GB, 40, ""),
    ]
    seed_index(media, {k: v for k, v in films.items() if k != "9"}, releases, poster=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            base = f"http://127.0.0.1:{listener.getsockname()[1]}/"
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 500}, locale="en-US")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                page.get_by_role("button", name="I am the owner").click()
                page.get_by_label("Server password").fill("test-password-long")
                page.locator("#login-form button.primary").click()
                page.goto(base + "#/media/video/tracker")
                frame = page.frame_locator("#media-frame")
                new = frame.locator('section[aria-label="New on the tracker"]')
                expect(new.locator(".media-row-card")).to_have_count(6, timeout=15000)
                plain = new.locator(".media-row-card", has_text="Mystery")
                expect(plain).to_have_count(1)
                frame.locator(".media-row-card", has_text="Dune").first.click()
                feature = frame.locator("#media-feature")
                expect(feature.get_by_text("Synopsis de Dune.")).to_be_visible()
                mark = "document.querySelectorAll('.media-row-card').forEach(c => c.__kept = true);"
                scroll = (
                    "const s = document.querySelector('.media-scroll'); s.scrollTop = 60;"
                    " window.scrollTo(0, 40);"
                    " const track = document.querySelector('.media-row-track');"
                    " return [s.scrollTop, scrollY, track.scrollLeft];"
                )
                handle = page.query_selector("#media-frame").content_frame()
                handle.evaluate(mark)
                before = handle.evaluate(f"(() => {{{scroll}}})()")
                # TMDb identifies the film: its facts arrive, and the index's revision moves.
                with media.lock, media.db:
                    media.db.execute(
                        "INSERT INTO film_meta (tmdb, title, original_title, year, overview,"
                        " genres, runtime, rating, poster) VALUES ('9', 'Mystère', 'Mystery',"
                        " '2012', 'Synopsis de Mystère.', '[\"Drame\"]', 100, '12', '')"
                    )
                    media.db.execute(
                        "UPDATE film_release SET manual='9' WHERE infohash=?", ("f" * 40,)
                    )
                media._films_changed()
                swapped = new.locator(".media-row-card", has_text="Mystère")
                expect(swapped).to_have_count(1, timeout=20000)
                expect(plain).to_have_count(0)
                after = handle.evaluate(
                    "[document.querySelector('.media-scroll').scrollTop, scrollY,"
                    " document.querySelector('.media-row-track').scrollLeft]"
                )
                assert after == before
                # Nothing else was drawn again, and the chosen film is still in the banner.
                kept = handle.evaluate(
                    "[...document.querySelectorAll('.media-row-card')].filter(c => c.__kept).length"
                )
                assert kept >= 5
                expect(feature.get_by_text("Synopsis de Dune.")).to_be_visible()
                # The Drame row took the film in too.
                drame = frame.locator('section[aria-label="Drame"]')
                expect(drame.locator(".media-row-card", has_text="Mystère")).to_have_count(1)
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=5)
