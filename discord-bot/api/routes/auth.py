"""
Authentication routes: login, token refresh
"""

from datetime import timedelta
from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from database.connection import get_db
from database.models import Moderator
from api.middleware.auth import (
    verify_password, create_access_token, Token, TokenData,
    get_current_user, hash_password,
)
from config.settings import settings
from utils.logger import logger

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    guild_id: int
    user_id: int
    password: str


class RegisterRequest(BaseModel):
    guild_id: int
    user_id: int
    username: str
    password: str
    is_admin: bool = False
    secret_key: str


@router.post("/login", response_model=Token, summary="Login und JWT-Token erhalten")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Moderator).where(
            Moderator.guild_id == data.guild_id,
            Moderator.user_id == data.user_id,
        )
    )
    mod = result.scalar_one_or_none()
    if not mod or not mod.api_token_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not verify_password(data.password, mod.api_token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    from sqlalchemy import update
    from datetime import datetime, timezone
    await db.execute(
        update(Moderator)
        .where(Moderator.id == mod.id)
        .values(last_login=datetime.now(timezone.utc))
    )
    await db.commit()

    token = create_access_token({
        "user_id": mod.user_id,
        "guild_id": mod.guild_id,
        "username": mod.username,
        "is_admin": mod.is_admin,
    })
    return Token(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/register", summary="Moderator-Account registrieren")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if data.secret_key != settings.api_secret_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid secret key")

    result = await db.execute(
        select(Moderator).where(
            Moderator.guild_id == data.guild_id,
            Moderator.user_id == data.user_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Moderator already exists")

    # Auto-create guild entry if bot not yet in server
    from database.models import Guild
    guild_result = await db.execute(select(Guild).where(Guild.id == data.guild_id))
    guild = guild_result.scalar_one_or_none()
    if not guild:
        guild = Guild(
            id=data.guild_id,
            name=f"Guild {data.guild_id}",
            is_active=True,
        )
        db.add(guild)
        await db.flush()

    mod = Moderator(
        guild_id=data.guild_id,
        user_id=data.user_id,
        username=data.username,
        api_token_hash=hash_password(data.password),
        is_admin=data.is_admin,
    )
    db.add(mod)
    await db.commit()
    return {"success": True, "message": "Moderator registered successfully"}


@router.get("/me", summary="Aktuellen Benutzer abfragen")
async def me(current_user: TokenData = Depends(get_current_user)):
    return {
        "user_id": current_user.user_id,
        "guild_id": current_user.guild_id,
        "username": current_user.username,
        "is_admin": current_user.is_admin,
    }
