from __future__ import annotations

import asyncio
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr, field_validator

from app.team.auth import COOKIE, DUMMY_HASH, LOCAL_USER, PASSWORDS, require_role
from app.workspace.store import ConflictError

router = APIRouter(prefix="/api", tags=["team"])
Role = Literal["owner", "editor", "reviewer"]


class EmailModel(BaseModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class Login(EmailModel):
    password: SecretStr = Field(min_length=1, max_length=128)


class Account(EmailModel):
    name: str = Field(min_length=2, max_length=80)
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter your name.")
        return value


class Setup(Account):
    setup_token: SecretStr = Field(min_length=20, max_length=200)
    workspace_name: str = Field(min_length=2, max_length=80)

    @field_validator("workspace_name")
    @classmethod
    def valid_workspace_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Enter a workspace name.")
        return value


class Join(Account):
    token: SecretStr = Field(min_length=20, max_length=200)


class Invite(EmailModel):
    role: Literal["editor", "reviewer"] = "reviewer"


class Access(BaseModel):
    role: Role
    active: bool


class PasswordChange(BaseModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


def auth(request: Request):
    if not request.app.state.settings.auth_enabled:
        raise HTTPException(409, "Team accounts are disabled in local demo mode.")
    return request.app.state.auth


def rate_limit(request: Request, email: str):
    host = request.client.host if request.client else "unknown"
    auth(request).reserve_attempt(host, email)


def establish(request: Request, response: Response, user: dict) -> dict:
    token, csrf = auth(request).session(user["id"])
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="strict",
        path="/",
        secure=request.app.state.settings.secure_cookies,
        max_age=auth(request).session_seconds,
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "user": user,
        "csrf_token": csrf,
        "auth_enabled": True,
        "setup_required": False,
        "workspace_name": auth(request).workspace_name(),
    }


@router.get("/auth/session")
async def session(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not request.app.state.settings.auth_enabled:
        return {
            "user": LOCAL_USER,
            "csrf_token": None,
            "auth_enabled": False,
            "setup_required": False,
            "workspace_name": "Personal workspace",
        }
    repository = auth(request)
    current = repository.resolve(request.cookies.get(COOKIE))
    return {
        "user": current["user"] if current else None,
        "csrf_token": current["csrf_token"] if current else None,
        "auth_enabled": True,
        "setup_required": repository.setup_required(),
        "workspace_name": repository.workspace_name() if current else "Your workspace",
    }


@router.post("/auth/setup", status_code=201)
async def setup(payload: Setup, request: Request, response: Response):
    rate_limit(request, payload.email)
    async with request.app.state.password_slots:
        hashed = await asyncio.to_thread(PASSWORDS.hash, payload.password.get_secret_value())
    try:
        user = auth(request).setup(
            payload.email,
            payload.name,
            hashed,
            payload.setup_token.get_secret_value(),
            payload.workspace_name.strip(),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from None
    return establish(request, response, user)


@router.post("/auth/login")
async def login(payload: Login, request: Request, response: Response):
    rate_limit(request, payload.email)
    account = auth(request).account(payload.email)
    async with request.app.state.password_slots:
        valid = await asyncio.to_thread(
            PASSWORDS.verify,
            payload.password.get_secret_value(),
            account["password_hash"] if account else DUMMY_HASH,
        )
    if not account or not account["active"] or not valid:
        raise HTTPException(401, "Email or password is incorrect.")
    return establish(request, response, auth(request).public(account))


@router.post("/auth/join", status_code=201)
async def join(payload: Join, request: Request, response: Response):
    rate_limit(request, payload.email)
    async with request.app.state.password_slots:
        hashed = await asyncio.to_thread(PASSWORDS.hash, payload.password.get_secret_value())
    try:
        user = auth(request).accept(
            payload.token.get_secret_value(), payload.email, payload.name, hashed
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return establish(request, response, user)


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    auth(request).logout(request.cookies.get(COOKIE, ""))
    response.delete_cookie(
        COOKIE,
        path="/",
        secure=request.app.state.settings.secure_cookies,
        httponly=True,
        samesite="strict",
    )
    return {"ok": True}


@router.post("/auth/password")
async def change_password(payload: PasswordChange, request: Request, response: Response):
    user = request.state.user
    rate_limit(request, user["email"])
    account = auth(request).account(user["email"])
    async with request.app.state.password_slots:
        valid = await asyncio.to_thread(
            PASSWORDS.verify, payload.current_password.get_secret_value(), account["password_hash"]
        )
        if not valid:
            raise HTTPException(400, "Current password is incorrect.")
        hashed = await asyncio.to_thread(PASSWORDS.hash, payload.new_password.get_secret_value())
    auth(request).change_password(user["id"], hashed)
    return establish(request, response, user)


@router.get("/team")
async def team(request: Request):
    repo = auth(request)
    owner = request.state.user["role"] == "owner"
    return {
        "name": repo.workspace_name(),
        "members": repo.members(),
        "invitations": repo.invitations() if owner else [],
    }


@router.post("/team/invitations", status_code=201)
async def invite(payload: Invite, request: Request):
    actor = require_role(request, "owner")
    try:
        info, token = auth(request).invite(payload.email, payload.role, actor)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    # A relative fragment keeps the token out of HTTP request/access logs and referrers.
    return {**info, "join_path": f"/#/join/{token}", "expires_in_days": 7}


@router.post("/team/invitations/{invite_id}/revoke")
async def revoke(invite_id: str, request: Request):
    actor = require_role(request, "owner")
    try:
        auth(request).revoke_invite(invite_id, actor)
    except KeyError:
        raise HTTPException(404, "Pending invitation not found.") from None
    return {"ok": True}


@router.put("/team/members/{user_id}")
async def update_member(user_id: str, payload: Access, request: Request):
    actor = require_role(request, "owner")
    try:
        auth(request).update_member(user_id, payload.role, payload.active, actor)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "Member not found.") from None
    return {"ok": True}
