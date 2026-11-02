"""Sign-up, sign-in and the session cookie.

New accounts must be verified before they can sign in (the original site says "ask the administrator to verify
this account"). The very first account is the owner and is verified automatically; verify later ones with
    python -m app.admin verify someone@example.com
"""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from . import db

router = APIRouter()
COOKIE = "mahadspace_session"
SESSION_DAYS = 30
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(candidate.hex(), digest)


def public(user) -> dict:
    return {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}


@router.post("/api/auth/register")
def register(body: RegisterIn):
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists.")
        first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        conn.execute("INSERT INTO users (email, display_name, password_hash, verified, created_at) VALUES (?, ?, ?, ?, ?)",
                     (email, body.display_name.strip(), hash_password(body.password), int(first), db.now()))
    return {"message": "Account created." if first else "Account created. An administrator must verify it before you can sign in.",
            "verified": first}


@router.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    with db.connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.strip().lower(),)).fetchone()
        if user is None or not check_password(body.password, user["password_hash"]):
            raise HTTPException(401, "Email or password is incorrect.")
        if not user["verified"]:
            raise HTTPException(403, "This account has not been verified yet. Ask the administrator to verify it.")
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
        conn.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                     (token, user["id"], db.now(), expires.isoformat(timespec="seconds")))
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=os.environ.get("MAHADSPACE_SECURE_COOKIE") == "on")
    return public(user)


@router.post("/api/auth/logout")
def logout(response: Response, mahadspace_session: str | None = Cookie(default=None)):
    if mahadspace_session:
        with db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (mahadspace_session,))
    response.delete_cookie(COOKIE)
    return {"message": "Signed out."}


def current_user(mahadspace_session: str | None = Cookie(default=None)) -> dict:
    if not mahadspace_session:
        raise HTTPException(401, "Sign in to continue.")
    with db.connect() as conn:
        row = conn.execute("SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id"
                           " WHERE s.token = ?", (mahadspace_session,)).fetchone()
        if row is None or row["expires_at"] < db.now():
            raise HTTPException(401, "Your session has ended. Sign in again.")
    return public(row)


@router.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return user
