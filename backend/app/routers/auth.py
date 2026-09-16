"""Router for authentication and user management endpoints."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.watchlist import Watchlist

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool

    class Config:
        from_attributes = True


class SetupStatusResponse(BaseModel):
    needs_setup: bool


class SetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)


def _login_response(username: str) -> JSONResponse:
    """Build the token + cookie response shared by login and first-boot setup."""
    is_prod = settings.is_production
    access_token = create_access_token(data={"sub": username})
    response = JSONResponse({"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_prod,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/",
    )
    return response


async def _user_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return result.scalar_one()


@router.get("/setup-status", response_model=SetupStatusResponse)
async def get_setup_status(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Public first-boot probe: true iff no user account exists yet.

    Leaks nothing beyond the empty/non-empty bit, which is required so the
    frontend setup wizard can choose between "create admin" and "login".
    """
    return {"needs_setup": await _user_count(db) == 0}


@router.post("/setup", response_model=Token)
async def setup_first_admin(
    body: SetupRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Single-use first-boot endpoint: create the initial admin account.

    Allowed only when the users table is empty. Creates the user as admin,
    ensures its Default watchlist exists (same as POST /users; the lifespan
    seed may have pre-created one for user id 1), and returns an
    authenticated token response so the client is logged in immediately.
    """
    if await _user_count(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed",
        )

    new_user = User(
        username=body.username,
        hashed_password=get_password_hash(body.password),
        is_admin=True,
    )
    db.add(new_user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed",
        )

    existing_default = await db.execute(
        select(Watchlist).where(
            Watchlist.user_id == new_user.id,
            Watchlist.name == "Default",
        )
    )
    if existing_default.scalar_one_or_none() is None:
        db.add(Watchlist(name="Default", user_id=new_user.id))
    await db.commit()
    return _login_response(new_user.username)


@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(User).where(User.username == form_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _login_response(user.username)


@router.post("/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(key="access_token", path="/")
    return response


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_user)],
):
    return current_user
