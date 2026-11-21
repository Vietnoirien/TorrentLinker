"""Paramètres → Utilisateurs: the Owner, or a Member allowed to manage Members, edits Members.

A manager never touches the Owner's account, never changes a Permission they do not hold
themselves, never edits their own Permissions or caps, and never changes how someone holding
more than they do signs in (ADR-0022).

Invitation and password links are one-time, valid 24 h, 3 or 7 days; the token travels in the
URL's fragment (`join#…`), so it never reaches a server log.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from torrentlinker.accounts import OWNER, Accounts, Actor, Caps, Permission
from torrentlinker.web.permissions import Audience, needs


class MemberCaps(BaseModel):
    requests_per_week: int | None = Field(default=None, ge=0, le=10_000)
    bytes_per_week: int | None = Field(default=None, ge=0, le=10**15)
    pending: int | None = Field(default=None, ge=0, le=10_000)


class Member(BaseModel):
    name: str = Field(max_length=100)
    login: str = Field(max_length=100)
    proxy_user: str = Field(default="", max_length=200)
    password: str = Field(default="", max_length=1024)
    permissions: list[Permission] = Field(default_factory=list, max_length=len(Permission))
    caps: MemberCaps = Field(default_factory=MemberCaps)


class ProxyUser(BaseModel):
    proxy_user: str = Field(default="", max_length=200)


class NewLink(BaseModel):
    days: int = 3
    base: str = Field(max_length=500)  # the address the Web UI is opened at, for the link


class Invitation(NewLink):
    name: str = Field(max_length=100)
    note: str = Field(default="", max_length=500)
    permissions: list[Permission] = Field(default_factory=list, max_length=len(Permission))
    caps: MemberCaps = Field(default_factory=MemberCaps)


class LinkToken(BaseModel):
    token: str = Field(max_length=100)


class LinkUse(LinkToken):
    password: str = Field(max_length=1024)
    name: str = Field(default="", max_length=100)
    login: str = Field(default="", max_length=100)


def shared_link(base: str, token: str, details: dict) -> dict:
    """The link to send, with its QR code as rows of modules the page draws."""
    import segno

    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "Open TorrentLinker at its usual address to create a link.")
    url = base.split("#")[0].rstrip("/") + "/join#" + token
    rows = segno.make(url, error="m", micro=False).matrix
    return {"url": url, "qr": ["".join("1" if m else "0" for m in row) for row in rows], **details}


def member_routes(
    app: FastAPI,
    accounts: Accounts,
    media,
    *,
    proxy: bool,
    signed_in: Callable[[str], JSONResponse],
) -> None:
    def actor(request: Request) -> Actor:
        return request.state.actor

    def answer(work):
        try:
            return work()
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    def current(account: str) -> dict:
        found = next((m for m in accounts.members() if m["id"] == account), None)
        if found is None:
            raise HTTPException(404, "This Member no longer exists.")
        return found

    def may_edit(editor: Actor, account: str, before: set[str], after: set[str]) -> None:
        if editor.owner:
            return
        if account == editor.account and before != after:
            raise PermissionError("Ask another manager to change your own Permissions.")
        lacking = {p for p in before ^ after if not editor.holds(Permission(p))}
        if lacking:
            raise PermissionError("You cannot grant or remove a Permission you do not hold.")

    def caps(body: Member, account: str) -> Caps:
        kept = accounts.caps(account).assistant_per_day
        if Permission.REQUEST not in body.permissions:
            return Caps(assistant_per_day=kept)  # caps need the Request Permission
        return Caps(**body.caps.model_dump(), assistant_per_day=kept)

    @app.get("/api/members")
    @needs(Permission.MANAGE_MEMBERS)
    def members(request: Request) -> dict:
        editor = actor(request)
        return {
            "members": accounts.members(),
            "proxy": proxy,
            "you": editor.account,
            "grantable": sorted(p.value for p in Permission if editor.holds(p)),
            **({"owner_proxy_user": accounts.owner_proxy_user()} if editor.owner else {}),
        }

    @app.post("/api/members/owner/proxy-user")
    def owner_proxy_user(body: ProxyUser) -> dict:
        # Undeclared: only the Owner names how the proxy sends them.
        answer(lambda: accounts.set_proxy_user(OWNER, body.proxy_user))
        return {"proxy_user": accounts.owner_proxy_user()}

    def no_links() -> None:
        if proxy:
            raise HTTPException(400, "The reverse proxy signs users in: links are not used.")

    @app.post("/api/members/invite")
    @needs(Permission.MANAGE_MEMBERS)
    def invite(body: Invitation, request: Request) -> dict:
        editor = actor(request)
        no_links()

        def work() -> tuple[str, str]:
            may_edit(editor, "", set(), {p.value for p in body.permissions})
            caps = (
                Caps(**body.caps.model_dump()) if Permission.REQUEST in body.permissions else Caps()
            )
            return accounts.invite(
                body.name,
                body.permissions,
                caps,
                days=body.days,
                inviter=editor.account,
                note=body.note,
            )

        account, token = answer(work)
        found = current(account)
        return {"member": found, "link": shared_link(body.base, token, found["link"])}

    def linkable(editor: Actor, account: str) -> dict:
        if account == OWNER:
            raise HTTPException(403, "The Owner's account cannot be edited here.")
        found = current(account)
        stronger = any(not editor.holds(Permission(p)) for p in found["permissions"])
        if stronger and not editor.owner:
            raise HTTPException(
                403, "Only the Owner can change how a Member with more Permissions signs in."
            )
        return found

    @app.post("/api/members/{account}/link")
    @needs(Permission.MANAGE_MEMBERS)
    def new_link(account: str, body: NewLink, request: Request) -> dict:
        """A new password link, or a new invitation for someone who has not joined yet."""
        editor = actor(request)
        no_links()
        linkable(editor, account)
        token = answer(
            lambda: accounts.password_link(account, days=body.days, inviter=editor.account)
        )
        found = current(account)
        return {"member": found, "link": shared_link(body.base, token, found["link"])}

    @app.post("/api/members/{account}/show-link")
    @needs(Permission.MANAGE_MEMBERS)
    def show_link(account: str, body: NewLink, request: Request) -> dict:
        linkable(actor(request), account)
        opened = accounts.open_link(account)
        if opened is None:
            raise HTTPException(404, "This link has expired or was used. Create a new one.")
        return {"link": shared_link(body.base, *opened)}

    @app.post("/api/members/{account}/cancel-link")
    @needs(Permission.MANAGE_MEMBERS)
    def cancel_link(account: str, request: Request) -> dict:
        linkable(actor(request), account)
        removed = answer(lambda: accounts.cancel_link(account))
        if removed:
            media.forget_account(account)
        return {"removed": removed}

    @app.post("/api/links/inspect")
    @needs(Audience.PUBLIC)
    def inspect_link(body: LinkToken) -> dict:
        no_links()
        found = accounts.link(body.token)
        if found is None:
            raise HTTPException(404, "This link is not valid.")
        return found

    @app.post("/api/links/redeem")
    @needs(Audience.PUBLIC)
    def redeem_link(body: LinkUse) -> JSONResponse:
        no_links()
        account = answer(
            lambda: accounts.redeem(body.token, body.password, name=body.name, login=body.login)
        )
        return signed_in(account)

    @app.post("/api/members")
    @needs(Permission.MANAGE_MEMBERS)
    def create(body: Member, request: Request) -> dict:
        editor = actor(request)
        if proxy and not body.proxy_user.strip():
            raise HTTPException(400, "Give the name your reverse proxy sends for this Member.")
        if not proxy and not body.password:
            raise HTTPException(400, "Choose a password for this Member.")

        def work() -> str:
            may_edit(editor, "", set(), {p.value for p in body.permissions})
            account = accounts.create(
                body.name,
                body.login,
                body.permissions,
                password=body.password,
                proxy_user=body.proxy_user,
            )
            accounts.set_caps(account, caps(body, account))
            return account

        return current(answer(work))

    @app.post("/api/members/{account}")
    @needs(Permission.MANAGE_MEMBERS)
    def update(account: str, body: Member, request: Request) -> dict:
        editor = actor(request)
        if account == OWNER:
            raise HTTPException(403, "The Owner's account cannot be edited here.")
        before = current(account)

        def work() -> None:
            granted = {p.value for p in body.permissions}
            may_edit(editor, account, set(before["permissions"]), granted)
            new_caps = caps(body, account)
            if account == editor.account and not editor.owner and vars(new_caps) != before["caps"]:
                raise PermissionError("Ask another manager to change your own caps.")
            signs_in = body.password or body.proxy_user.strip() != before["proxy_user"]
            stronger = any(not editor.holds(Permission(p)) for p in before["permissions"])
            if signs_in and stronger:
                # Otherwise a manager could sign in as someone holding more than they do.
                raise PermissionError(
                    "Only the Owner can change how a Member with more Permissions signs in."
                )
            accounts.update(account, body.name, body.login, body.proxy_user)
            accounts.grant(account, body.permissions)
            accounts.set_caps(account, new_caps)
            if body.password:
                accounts.set_password(account, body.password)

        answer(work)
        return current(account)

    @app.post("/api/members/{account}/{action}")
    @needs(Permission.MANAGE_MEMBERS, action={"disable", "enable", "delete"})
    def manage(account: str, action: str, request: Request) -> dict:
        editor = actor(request)
        if account == OWNER:
            raise HTTPException(403, "The Owner's account cannot be disabled or deleted.")
        if account == editor.account and not editor.owner:
            raise HTTPException(403, "Ask another manager to disable or delete your account.")
        current(account)
        if action == "delete":
            answer(lambda: accounts.delete(account))
            media.forget_account(account)
            return {"ok": True}
        answer(lambda: accounts.disable(account, action == "disable"))
        return current(account)
