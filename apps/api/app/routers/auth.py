"""Auth endpoints: login, refresh, logout, me.

Login contract (consistent with QUICKSTART.md and the web UI):
- JSON body: {"email": "...", "password": "..."} -> 200 Token | 401 | 422
- OAuth2 form body (username or email + password) is still accepted for
  OpenAPI/Swagger "Authorize" flows.

Refresh-token handling (server-side rotation + revocation):
- Login and refresh set the refresh token as an HttpOnly cookie (the
  browser never exposes it to JavaScript). The JSON body still carries it
  for non-browser API clients (curl, scripts, evals).
- /auth/refresh accepts the token from the JSON body (API clients, checked
  as-is) or the HttpOnly cookie (browsers) - never from the URL/query
  (query strings leak into logs).
- Every refresh ROTATES the token: the presented jti is added to the
  revoked_refresh_tokens deny list and a fresh token is issued. Presenting
  an already-revoked jti (a replay/theft signal) is rejected with 401 and
  audited.
- /auth/logout revokes the presented refresh token and clears the cookie.

Security:
- Uniform 401 message for unknown email and wrong password (no user
  enumeration), with a dummy bcrypt verify when the user is missing so
  response timing stays comparable.
- Sliding-window rate limit on failed logins (5 per 5 minutes per
  client+identifier). Redis-backed when Redis is reachable (multi-worker
  safe); falls back to per-process in-memory limiting otherwise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import settings
from apps.api.app.core.db import get_session
from apps.api.app.core.rate_limit import get_login_limiter
from apps.api.app.models.audit import AuditLog
from apps.api.app.models.refresh_token import RevokedRefreshToken
from apps.api.app.models.user import User

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    """JSON login body (the documented contract)."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=4096)


class LogoutRequest(BaseModel):
    """Optional logout body - the cookie alone is enough for browsers."""

    refresh_token: str | None = Field(default=None, min_length=10, max_length=4096)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str


# --- Login rate limiting ------------------------------------------------------
# Backend lives in core.rate_limit (Redis when available, in-memory fallback);
# thresholds come from settings (RATE_LIMIT_MAX_FAILURES /
# RATE_LIMIT_WINDOW_SECONDS).


def _client_key(request: Request) -> str:
    # Best-effort client identifier; behind a proxy this is the proxy IP
    # (documented limitation - real deployments should pass X-Forwarded-For
    # from a trusted proxy).
    return request.client.host if request.client else "unknown"


# --- Token helpers -----------------------------------------------------------


def _create_token(subject: str, expires_minutes: int, token_type: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "type": token_type,
    }
    if token_type == "refresh":
        # Unique JWT ID - the handle for the revocation list.
        payload["jti"] = uuid.uuid4().hex
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _refresh_max_age_seconds() -> int:
    return settings.jwt_refresh_token_expire_days * 24 * 60 * 60


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Store the refresh token where JavaScript cannot read it."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=_refresh_max_age_seconds(),
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path="/",
    )


async def _revoke_refresh(session: AsyncSession, *, user_id: str, payload: dict) -> None:
    """Record the token's jti on the deny list (idempotent)."""
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not jti or not exp:
        return
    existing = await session.get(RevokedRefreshToken, str(jti))
    if existing is not None:
        return
    session.add(
        RevokedRefreshToken(
            jti=str(jti),
            user_id=uuid.UUID(str(user_id)),
            expires_at=datetime.fromtimestamp(float(exp), tz=UTC),
        )
    )


# A real bcrypt hash of an unguessable value; verified when the user does not
# exist so that unknown-email and wrong-password responses take similar time.
_DUMMY_HASH = User.hash_password("not-a-real-password")


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None:
        # Timing shim: burn a bcrypt verify so unknown-email is not measurably
        # faster than wrong-password (mitigates user enumeration).
        from apps.api.app.models.user import pwd_context

        pwd_context.verify(password, _DUMMY_HASH)
        return None
    if not user.verify_password(password):
        return None
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            raise credentials_exc
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError as e:
        raise credentials_exc from e

    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise credentials_exc
    return user


@router.post("/login", response_model=Token, summary="Login (JSON or OAuth2 form)")
async def login(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Token:
    """Issue access + refresh tokens.

    Body (documented contract): `{"email": "...", "password": "..."}`.
    OAuth2 `x-www-form-urlencoded` with `username` (or `email`) + `password`
    is also accepted for Swagger's Authorize button.

    The refresh token is returned in the body (non-browser clients) AND set
    as an HttpOnly cookie (browsers - JavaScript can never read it).
    """
    content_type = (request.headers.get("content-type") or "").lower()
    identifier: str
    password: str

    if "application/json" in content_type:
        try:
            raw = await request.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid JSON body"
            ) from exc
        try:
            body = LoginRequest(email=raw["email"], password=raw["password"])
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Missing required field: {exc}",
            ) from exc
        except Exception as exc:  # pydantic ValidationError and friends
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid login payload"
            ) from exc
        identifier, password = body.email, body.password
    else:
        form = OAuth2PasswordRequestForm(
            username=str((await request.form()).get("username") or ""),
            password=str((await request.form()).get("password") or ""),
        )
        # Accept "email" as the form identifier too (frontends often send it).
        if not form.username:
            form = OAuth2PasswordRequestForm(
                username=str((await request.form()).get("email") or ""),
                password=str((await request.form()).get("password") or ""),
            )
        identifier, password = form.username, form.password
        if not identifier or not password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="username/email and password are required",
            )

    client_key = _client_key(request)
    limiter = await get_login_limiter()
    if await limiter.is_blocked(client_key, identifier):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(int(settings.rate_limit_window_seconds))},
        )

    user = await authenticate_user(session, identifier, password)
    if user is None:
        await limiter.record_failure(client_key, identifier)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    refresh = _create_token(
        str(user.id), settings.jwt_refresh_token_expire_days * 24 * 60, "refresh"
    )
    _set_refresh_cookie(response, refresh)
    return Token(
        access_token=_create_token(
            str(user.id), settings.jwt_access_token_expire_minutes, "access"
        ),
        refresh_token=refresh,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: RefreshRequest | None = None,
) -> Token:
    """Exchange a valid refresh token for new tokens (with rotation).

    Token sources: the JSON body if present (API clients; validated as-is),
    otherwise the HttpOnly cookie (browser flow) - never the URL/query.
    The presented token is revoked (its jti joins the deny list) and a
    brand-new pair is issued, so each refresh token can be used exactly
    once. Replaying a rotated token is a theft signal and is rejected with
    401 + an audit record.
    """
    presented = (
        body.refresh_token if body is not None and body.refresh_token else None
    ) or request.cookies.get(settings.refresh_cookie_name)
    if not presented:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    credentials_exc = HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        payload = jwt.decode(presented, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "refresh":
            raise credentials_exc
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti:
            raise credentials_exc
    except JWTError as e:
        raise credentials_exc from e

    # Reuse detection: a jti already on the deny list means this token was
    # rotated or logged out earlier - someone is replaying it.
    if await session.get(RevokedRefreshToken, str(jti)) is not None:
        session.add(
            AuditLog(
                actor_id=uuid.UUID(str(user_id)),
                action="auth.refresh_reuse_detected",
                target=str(jti),
                metadata_={"reason": "revoked jti presented"},
            )
        )
        await session.commit()  # persist the audit row before the 401 rollback
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise credentials_exc

    # Rotate: the presented token dies, a fresh one is issued.
    await _revoke_refresh(session, user_id=str(user.id), payload=payload)
    refresh = _create_token(
        str(user.id), settings.jwt_refresh_token_expire_days * 24 * 60, "refresh"
    )
    _set_refresh_cookie(response, refresh)
    return Token(
        access_token=_create_token(
            str(user.id), settings.jwt_access_token_expire_minutes, "access"
        ),
        refresh_token=refresh,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout")
async def logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    body: LogoutRequest | None = None,
) -> None:
    """Revoke the presented refresh token and clear the cookie.

    Idempotent: calling logout without any token is a no-op that still
    returns 204. Browsers send the HttpOnly cookie automatically; API
    clients may pass `{"refresh_token": "..."}` in the body (which takes
    precedence, same as /auth/refresh).
    """
    presented = (
        body.refresh_token if body is not None and body.refresh_token else None
    ) or request.cookies.get(settings.refresh_cookie_name)
    if presented:
        try:
            payload = jwt.decode(
                presented, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
            )
            if payload.get("type") == "refresh" and payload.get("sub") and payload.get("jti"):
                await _revoke_refresh(session, user_id=str(payload["sub"]), payload=payload)
        except JWTError:
            pass  # invalid/expired token: nothing left to revoke
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserOut)
async def me(current: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut(
        id=str(current.id), email=current.email, name=current.name, role=current.role_slug
    )
