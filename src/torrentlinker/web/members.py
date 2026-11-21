"""Paramètres → Utilisateurs: the Owner, or a Member allowed to manage Members, edits Members.

A manager never touches the Owner's account, never changes a Permission they do not hold
themselves, never edits their own Permissions or caps, and never changes how someone holding
more than they do signs in (ADR-0022).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from torrentlinker.accounts import OWNER, Accounts, Actor, Caps, Permission
from torrentlinker.web.permissions import needs


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


def member_routes(app: FastAPI, accounts: Accounts, media, *, proxy: bool) -> None:
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
