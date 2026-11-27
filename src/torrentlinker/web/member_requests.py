"""Requests and Wishes, the Member's side: ask for a tracker film, wish for one, follow them.

A Member never downloads: "Demander" makes a Request an Approver answers (#134). The caps
are checked at sending; a reached cap refuses with its reason and the next reset (409).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from torrentlinker.accounts import OWNER_ACTOR, PICKING, Actor, Permission
from torrentlinker.member_requests import CapReached, FilmAsk, Requests
from torrentlinker.request_approval import RequestApproval
from torrentlinker.web.permissions import Audience, needs

NOT_FOUND = "This Request no longer exists."


class TrackerRequest(BaseModel):
    film: str = Field(pattern=r"^[a-z]+-[0-9a-f]{1,16}$")


class SeriesRequest(BaseModel):
    series: str = Field(pattern=r"^(tv|title|release)-[0-9a-f]{1,40}$")
    seasons: list[int] = Field(max_length=100)
    follow: bool = False


class Follow(BaseModel):
    series: str = Field(pattern=r"^(tv|title|release)-[0-9a-f]{1,40}$")
    on: bool


class Wish(BaseModel):
    title: str = Field(max_length=200)
    year: str = Field(default="", max_length=4)
    note: str = Field(default="", max_length=500)


class Answer(BaseModel):
    infohash: str = Field(default="", pattern="^([0-9a-fA-F]{40})?$")
    note: str = Field(default="", max_length=500)


def request_routes(app: FastAPI, requests: Requests, media, household_asks) -> None:
    approval = RequestApproval(media)
    app.state.request_approval = approval

    def actor(request: Request) -> Actor:
        return request.state.actor

    def refused(error: CapReached) -> JSONResponse:
        return JSONResponse(
            {"detail": str(error), "cap": error.cap, "reset": error.reset}, status_code=409
        )

    def mine(account: str) -> dict:
        approval.refresh(requests)
        rows = requests.mine(account)
        return {
            "requests": rows,
            "quota": requests.quota(account),
            # Household Asks wait here too: a Viewer's ask the holder has not yet opened is new.
            "household": household_asks.household(account),
            "unread": sum(1 for r in rows if r["unread"]) + household_asks.unseen(account),
            "following": app.state.series_follows.following(account),
        }

    @app.get("/api/requests")
    @needs(Audience.ACCOUNT_HOLDER)
    def listing(request: Request) -> dict:
        return mine(actor(request).account)

    @app.post("/api/requests/seen")
    @needs(Audience.ACCOUNT_HOLDER)
    def seen(request: Request) -> dict:
        requests.seen(actor(request).account)
        household_asks.seen(actor(request).account)
        return mine(actor(request).account)

    @app.post("/api/requests")
    @needs(Permission.REQUEST)
    def ask(body: TrackerRequest, request: Request):
        """A Request for a Tracker Film the Member sees; the Approver chooses the release."""
        try:
            return app.state.member_workspace.ask(actor(request), body.film)
        except KeyError:
            raise HTTPException(404, "This film is not on the tracker.") from None
        except CapReached as error:
            return refused(error)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/requests/series")
    @needs(Permission.REQUEST)
    def ask_series(body: SeriesRequest, request: Request):
        """A Request for chosen seasons of a Tracker Series: one per season, shared with the
        Members asking for the same season and charged as a film is (ADR-0030). The Member
        never names a release, and never asks for an episode."""
        from torrentlinker import tracker_series_view as view

        found, client = actor(request), approval.client_id
        try:
            panel = view.detail(media, client, body.series, found)
        except KeyError:
            raise HTTPException(404, "This series is not on the tracker.") from None
        if not found.holds(
            Permission.ANIME if panel["series_kind"] == "anime" else Permission.SERIES
        ):
            raise HTTPException(403, "This is not allowed for your account.")
        asked = view.quote(media, client, body.series, body.seasons, found)
        if not asked["seasons"]:
            if not body.follow:
                raise HTTPException(409, "None of these seasons can be asked for.")
            app.state.series_follows.follow(found.account, body.series)
            return {"requests": []}
        each = -(-asked["size"] // len(asked["seasons"]))  # an Intégrale's size is split
        entry = next(e for e in media.series_index() if e["id"] == body.series)
        packs = view.preselect(
            entry, asked["seasons"], media.series_score(client), media.series_order(client),
            len(panel["seasons"]),
        )["per_season"]  # fmt: skip
        made, failed = [], ""
        for n in asked["seasons"]:
            size = each if asked["integrale"] else int(packs[n]["size"])
            try:
                made.append(
                    requests.ask_film(
                        found.account,
                        FilmAsk(f"{body.series}:{n}", f"{panel['title']} · saison {n}",
                                str(panel["year"]), size),
                    )
                )  # fmt: skip
            except CapReached as error:
                if not made:
                    return refused(error)
                failed = str(error)
                break
            except ValueError as error:  # already asked for this season
                failed = str(error)
        if not made:
            raise HTTPException(409, failed)
        if body.follow:
            app.state.series_follows.follow(found.account, body.series)
        return {"requests": made}

    @app.post("/api/requests/series/follow")
    @needs(Permission.REQUEST)
    def follow_series(body: Follow, request: Request) -> dict:
        """Suivre la série, or stop following it: nothing downloads, a pending Request waits."""
        account = actor(request).account
        follows = app.state.series_follows
        if body.on:
            from torrentlinker import tracker_series_view as view

            try:
                view.detail(media, approval.client_id, body.series, actor(request))
            except KeyError:
                raise HTTPException(404, "This series is not on the tracker.") from None
            follows.follow(account, body.series)
        else:
            follows.unfollow(account, body.series)
        return {"following": follows.following(account)}

    # Household Asks (decision 24): a Viewer asks its account holder, who answers.

    def viewer_of(request: Request) -> Actor:
        found = actor(request)
        if not found.viewer or found.viewer == PICKING:
            raise HTTPException(403, "Only a profile on a Shared Screen asks its account holder.")
        return found

    @app.get("/api/household-asks")
    @needs(Audience.SIGNED_IN)
    def viewer_asks(request: Request) -> dict:
        found = viewer_of(request)
        return {**household_asks.mine(found.account, found.viewer), "can_ask": found.asks}

    @app.post("/api/household-asks")
    @needs(Audience.SIGNED_IN)
    def viewer_ask(body: TrackerRequest, request: Request):
        found = viewer_of(request)
        if not found.asks or not media.sees_tracker(found):
            raise HTTPException(403, "The account holder has not allowed this profile to ask.")
        client = approval.client_id
        try:
            film = media.tracker_film_detail(client, media.setup(client), found, body.film)
            return household_asks.ask(
                found.account,
                found.viewer,
                found.screen,
                FilmAsk(body.film, film["title"], film["year"], int(film["quote"])),
            )
        except KeyError:
            raise HTTPException(404, "This film is not on the tracker.") from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/household-asks/{identifier}/cancel")
    @needs(Audience.SIGNED_IN)
    def viewer_cancel(identifier: str, request: Request) -> dict:
        found = viewer_of(request)
        try:
            return household_asks.cancel(found.account, found.viewer, identifier)
        except KeyError:
            raise HTTPException(404, "This ask no longer exists.") from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/household-asks/{identifier}/accept")
    @needs(Audience.ACCOUNT_HOLDER)
    def holder_accept(identifier: str, request: Request):
        found = actor(request)
        if not found.holds(Permission.REQUEST):
            raise HTTPException(403, "Your account cannot make Requests.")
        try:
            return household_asks.accept(found.account, identifier)
        except KeyError:
            raise HTTPException(404, "This ask no longer exists.") from None
        except CapReached as error:
            return refused(error)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/household-asks/{identifier}/refuse")
    @needs(Audience.ACCOUNT_HOLDER)
    def holder_refuse(identifier: str, body: Answer, request: Request) -> dict:
        try:
            return household_asks.refuse(actor(request).account, identifier, body.note)
        except KeyError:
            raise HTTPException(404, "This ask no longer exists.") from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/wishes")
    @needs(Permission.WISH)
    def wish(body: Wish, request: Request):
        try:
            return requests.wish(actor(request).account, body.title, body.year, body.note)
        except CapReached as error:
            return refused(error)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/requests/{identifier}/cancel")
    @needs(Permission.REQUEST, Permission.WISH)
    def cancel(identifier: str, request: Request) -> dict:
        try:
            return requests.cancel(actor(request).account, identifier)
        except KeyError:
            raise HTTPException(404, NOT_FOUND) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/requests/review")
    @needs(Permission.APPROVE)
    def review() -> dict:
        approval.refresh(requests)
        rows = requests.review()
        client = approval.client_id
        for row in rows:
            row["score"] = None
            row["releases"] = []
            from torrentlinker import tracker_series_view as view

            if view.split_key(row["film"]):
                pending = [
                    p[1]
                    for r in rows
                    if r["state"] == "pending"
                    and (p := view.split_key(r["film"]))
                    and p[0] == view.split_key(row["film"])[0]  # type: ignore[index]
                ]
                found = view.approver_choices(
                    media, client, row["film"], pending, media.series_score(client),
                    media.series_order(client),
                )  # fmt: skip
                if found:
                    row.update(
                        found, below_threshold=False, in_library=False, film_id=found["series_id"]
                    )
            elif row["film"]:
                # The film's grouped releases, the pre-selected first: the Approver chooses.
                try:
                    film = media.tracker_film_detail(
                        client, media.setup(client), OWNER_ACTOR, row["film"]
                    )
                except KeyError:
                    film = None
                if film:
                    row["releases"] = film["releases"]
                    row["preselected"] = film["tracker"]["hash"]
                    row["below_threshold"] = film["below_threshold"]
                    row["in_library"] = film["in_library"]
                    row["film_id"] = film["id"]
            if row["infohash"]:
                try:
                    entry = media.tracker_entry(client, row["infohash"])
                    row["score"] = media._score(
                        media.agent.setup.settings.release_score,
                        row["release"],
                        row["chosen_size"] or row["size"],
                        entry.get("facts") or {},
                    ).get("score")
                except ValueError:
                    pass
        return {
            "requests": rows,
            "margin": approval.margin(sum(r["size"] or 0 for r in rows if r["state"] == "pending")),
        }

    @app.get("/api/requests/releases")
    @needs(Permission.APPROVE)
    def releases(q: str = "") -> dict:
        return {"releases": approval.choices(q[:200])}

    @app.get("/api/requests/releases/{infohash}/description")
    @needs(Permission.APPROVE)
    def description(infohash: str) -> dict:
        """A release's torrent description as plain text, for the Approver to read before
        choosing it. A Member never gets one."""
        import html
        import re

        from torrentlinker.torrent_details import parse_details

        if not re.fullmatch(r"[0-9a-fA-F]{40}", infohash):
            raise HTTPException(404, "Unknown release.")
        try:
            raw = media.setup(approval.client_id).indexer().torrent_json(infohash.lower())
            text = html.unescape(re.sub(r"<[^>]+>", " ", parse_details(raw).description))
        except Exception:
            return {"text": "", "unavailable": True}  # tr4ker's, or the Indexer not answering
        return {"text": re.sub(r"\s+", " ", text).strip()[:4000], "unavailable": False}

    def preselected(identifier: str) -> str:
        """The film's best release now, for an acceptance that chose none."""
        row = requests.get(identifier)
        if not row["film"] or row["infohash"]:
            return ""
        client = approval.client_id
        from torrentlinker import tracker_series_view as view

        if view.split_key(row["film"]):
            siblings = [
                p[1]
                for r in requests.review(group=False)
                if r["state"] == "pending"
                and (p := view.split_key(r["film"]))
                and p[0] == view.split_key(row["film"])[0]  # type: ignore[index]
            ]
            found = view.approver_choices(
                media, client, row["film"], siblings, media.series_score(client),
                media.series_order(client),
            )  # fmt: skip
            if not found or not found["preselected"]:
                raise ValueError("This season has no pack now. Refuse it or wait.")
            return str(found["preselected"])
        try:
            found = media.tracker_film_detail(client, media.setup(client), OWNER_ACTOR, row["film"])
        except KeyError:
            raise ValueError("This film has no seeded release now. Refuse it or wait.") from None
        return str(found["tracker"]["hash"])

    def answer(identifier: str, body: Answer, request: Request, action: str) -> dict:
        try:
            infohash = body.infohash.lower()
            if not infohash and action == "accept":
                infohash = preselected(identifier)
            release = approval.release(infohash) if infohash else None
            row = requests.answer(
                identifier,
                actor(request).account,
                release=release,
                note=body.note,
                retry=action == "retry",
                refuse=action == "refuse",
            )
        except KeyError:
            raise HTTPException(404, NOT_FOUND) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        if action != "refuse":
            try:
                approval.send(row["infohash"])
            except Exception:
                # Provider errors can contain URLs, credentials or local paths. Keep those
                # out of the Request seen by a Member, including the shared timeline.
                requests.move_group(
                    identifier, "send_failed", "", "Sending failed. Check the client and retry."
                )
            else:
                requests.move_group(identifier, "sent", "")
        return requests.get(identifier)

    @app.post("/api/requests/{identifier}/accept")
    @needs(Permission.APPROVE)
    def accept(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "accept")

    @app.post("/api/requests/{identifier}/resolve")
    @needs(Permission.APPROVE)
    def resolve(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "accept")

    @app.post("/api/requests/{identifier}/retry")
    @needs(Permission.APPROVE)
    def retry(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "retry")

    @app.post("/api/requests/{identifier}/refuse")
    @needs(Permission.APPROVE)
    def refuse(identifier: str, body: Answer, request: Request) -> dict:
        return answer(identifier, body, request, "refuse")

    @app.get("/api/requests/artwork/{infohash}")
    @needs(Permission.APPROVE)
    def artwork(infohash: str) -> FileResponse:
        if len(infohash) != 40 or any(c not in "0123456789abcdef" for c in infohash):
            raise HTTPException(404, "Artwork unavailable.")
        try:
            path = media.tracker_artwork(approval.client_id, infohash)
        except (ValueError, OSError):
            path = None
        if path is None or not path.is_file():
            raise HTTPException(404, "Artwork unavailable.")
        return FileResponse(path)
