"""Requests and Wishes, the Member's side: ask for a tracker film, wish for one, follow them.

A Member never downloads: "Demander" makes a Request an Approver answers (#134). The caps
are checked at sending; a reached cap refuses with its reason and the next reset (409).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from torrentlinker.accounts import OWNER_ACTOR, Actor, Permission
from torrentlinker.member_requests import CapReached, Requests
from torrentlinker.request_approval import RequestApproval
from torrentlinker.web.permissions import Audience, needs

NOT_FOUND = "This Request no longer exists."


class TrackerRequest(BaseModel):
    film: str = Field(pattern=r"^[a-z]+-[0-9a-f]{1,16}$")


class Wish(BaseModel):
    title: str = Field(max_length=200)
    year: str = Field(default="", max_length=4)
    note: str = Field(default="", max_length=500)


class Answer(BaseModel):
    infohash: str = Field(default="", pattern="^([0-9a-fA-F]{40})?$")
    note: str = Field(default="", max_length=500)


def request_routes(app: FastAPI, requests: Requests, media) -> None:
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
            "unread": sum(1 for r in rows if r["unread"]),
        }

    @app.get("/api/requests")
    @needs(Audience.ACCOUNT_HOLDER)
    def listing(request: Request) -> dict:
        return mine(actor(request).account)

    @app.post("/api/requests/seen")
    @needs(Audience.ACCOUNT_HOLDER)
    def seen(request: Request) -> dict:
        requests.seen(actor(request).account)
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
            if row["film"]:
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
