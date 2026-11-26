"""Member reads use their Requests, never an Owner queue or Torrent Client snapshot."""

from fastapi import FastAPI, HTTPException, Query, Request

from torrentlinker.accounts import Actor, Permission
from torrentlinker.member_requests import ACCEPTED, FilmAsk
from torrentlinker.web.permissions import needs


class MemberWorkspace:
    def __init__(self, requests, approval, media):
        self.requests, self.approval, self.media = requests, approval, media

    @staticmethod
    def require(actor: Actor, permission: Permission) -> None:
        if actor.viewer or not actor.holds(permission):
            raise PermissionError("Your account does not have the Permission for this.")

    def search(self, actor: Actor, query: str) -> list[dict]:
        """Tracker Films by title, as the Films page lists them: no release is named."""
        if not query.strip() or not self.media.sees_tracker(actor):
            return []
        client = self.approval.client_id
        page = self.media.tracker_films_listing(
            client, self.media.setup(client), actor, q=query[:200], limit=60
        )
        return page["rows"]

    def ask(self, actor: Actor, film: str) -> dict:
        """A Member's Request for a Tracker Film they see. KeyError when they do not see it."""
        if not self.media.sees_tracker(actor):
            raise KeyError(film)
        client = self.approval.client_id
        found = self.media.tracker_film_detail(client, self.media.setup(client), actor, film)
        return self.requests.ask_film(
            actor.account, FilmAsk(film, found["title"], found["year"], int(found["quote"]))
        )

    def queue(self, actor: Actor) -> list[dict]:
        self.require(actor, Permission.QUEUE)
        return [
            {key: row[key] for key in ("id", "title", "year", "release", "size", "state")}
            for row in self.requests.mine(actor.account)
            if row["state"] in ACCEPTED
        ]

    def torrents(self, actor: Actor) -> list[dict]:
        self.require(actor, Permission.TORRENTS)
        requested = {
            r["infohash"]: r for r in self.requests.mine(actor.account) if r["state"] in ACCEPTED
        }
        if not requested:
            return []
        client = self.media.setup(self.approval.client_id).client()
        return [
            {
                "id": requested[torrent.hash.lower()]["id"],
                "title": requested[torrent.hash.lower()]["title"],
                "size": torrent.size,
                "progress": torrent.progress,
                "state": "complete" if torrent.progress >= 1 else "downloading",
            }
            for torrent in client.torrents(with_files=False)
            if torrent.hash.lower() in requested
        ]


def member_workspace_routes(app: FastAPI, requests, approval, media) -> None:
    workspace = MemberWorkspace(requests, approval, media)
    app.state.member_workspace = workspace

    def read(request: Request, permission: Permission, work):
        actor = request.state.actor
        try:
            workspace.require(actor, permission)
            return {"rows": work(actor)}
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error

    @app.get("/api/member-workspace/search")
    @needs(Permission.FILMS)
    def search(request: Request, q: str = Query("", max_length=200)) -> dict:
        return read(request, Permission.FILMS, lambda actor: workspace.search(actor, q))

    @app.get("/api/member-workspace/queue")
    @needs(Permission.QUEUE)
    def queue(request: Request) -> dict:
        return read(request, Permission.QUEUE, workspace.queue)

    @app.get("/api/member-workspace/torrents")
    @needs(Permission.TORRENTS)
    def torrents(request: Request) -> dict:
        return read(request, Permission.TORRENTS, workspace.torrents)
