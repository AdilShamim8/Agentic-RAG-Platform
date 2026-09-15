"""Auth endpoints: login, refresh, logout, me."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import settings
from apps.api.app.core.db import get_session
from apps.api.app.models.user import User

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str


def _create_token(subject: str, expires_minutes: int, token_type: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "type": token_type,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None or not user.verify_password(password):
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


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Token:
    user = await authenticate_user(session, form.username, form.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return Token(
        access_token=_create_token(
            str(user.id), settings.jwt_access_token_expire_minutes, "access"
        ),
        refresh_token=_create_token(
            str(user.id), settings.jwt_refresh_token_expire_days * 24 * 60, "refresh"
        ),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Token:
    credentials_exc = HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        payload = jwt.decode(
            refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type") != "refresh":
            raise credentials_exc
        user_id = payload.get("sub")
    except JWTError as e:
        raise credentials_exc from e

    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise credentials_exc

    return Token(
        access_token=_create_token(
            str(user.id), settings.jwt_access_token_expire_minutes, "access"
        ),
        refresh_token=_create_token(
            str(user.id), settings.jwt_refresh_token_expire_days * 24 * 60, "refresh"
        ),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserOut)
async def me(current: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut(
        id=str(current.id), email=current.email, name=current.name, role=current.role_slug
    )
