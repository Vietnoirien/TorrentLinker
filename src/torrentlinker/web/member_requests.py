"""Requests and Wishes, the Member's side: ask for a tracker film, wish for one, follow them.

A Member never downloads: "Demander" makes a Request an Approver answers (#134). The caps
are checked at sending; a reached cap refuses with its reason and the next reset (409).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from torrentlinker.accounts import Actor, Permission
from torrentlinker.member_requests import CapReached, Release, Requests
from torrentlinker.web.permissions import Audience, needs

NOT_FOUND = "This Request no longer exists."


class TrackerRequest(BaseModel):
    infohash: str = Field(pattern="^[0-9a-fA-F]{40}$")


class Wish(BaseModel):
    title: str = Field(max_length=200)
    year: str = Field(default="", max_length=4)
    note: str = Field(default="", max_length=500)


def request_routes(app: FastAPI, requests: Requests, media) -> None:
    def actor(request: Request) -> Actor:
        return request.state.actor

    def refused(error: CapReached) -> JSONResponse:
        return JSONResponse(
            {"detail": str(error), "cap": error.cap, "reset": error.reset}, status_code=409
        )

    def mine(account: str) -> dict:
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
        """A Request for a tracker film the Member sees; the server reads its release."""
        found = actor(request)
        if not media.sees_tracker(found):
            raise HTTPException(404, "This tracker release is no longer suggested.")
        client = media.agent.setup.settings.default_client_id
        try:
            entry = media.tracker_entry(client, body.infohash.lower())
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        facts, best = entry.get("facts") or {}, entry["release"]
        release = Release(
            best["hash"],
            best["name"],
            int(best["size"]),
            facts.get("title") or entry.get("title") or best["name"],
            str(facts.get("year") or entry.get("year") or ""),
        )
        try:
            return requests.ask(found.account, release)
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
