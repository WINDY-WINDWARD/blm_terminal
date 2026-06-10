"""Router for user management endpoints (admin only)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_user, get_password_hash
from app.database import get_db
from app.models.user import User
from app.models.watchlist import Watchlist
from app.routers.auth import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)
    is_admin: bool = False


@router.post("", response_model=UserResponse)
async def create_user(
    user_in: UserCreate,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Check if username already exists
    stmt = select(User).where(User.username == user_in.username)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )
        
    new_user = User(
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        is_admin=user_in.is_admin,
    )
    db.add(new_user)
    await db.flush()

    watchlist = Watchlist(name="Default", user_id=new_user.id)
    db.add(watchlist)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@router.get("", response_model=list[UserResponse])
async def list_users(
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(User)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    await db.delete(user)
    await db.commit()


class PasswordChange(BaseModel):
    password: str = Field(..., min_length=8)


@router.put("/{user_id}/password")
async def change_user_password(
    user_id: int,
    body: PasswordChange,
    admin: Annotated[User, Depends(get_admin_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(body.password)
    await db.commit()
    return {"ok": True}
