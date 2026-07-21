"""
User routes: GET /users, GET /users/{user_id}, PATCH /user, GET /trust, GET /risk
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, update
from typing import Optional
from pydantic import BaseModel
from database.connection import get_db
from database.models import User, RiskRecord, AIAnalysis
from api.middleware.auth import get_current_user, TokenData
from utils.logger import logger

router = APIRouter(prefix="/users", tags=["Users"])


class UserUpdateRequest(BaseModel):
    notes: Optional[str] = None
    trust_score: Optional[float] = None


@router.get("", summary="Alle Benutzer eines Servers auflisten")
async def get_users(
    guild_id: int = Query(..., description="Server-ID"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("message_count", regex="^(message_count|trust_score|risk_score|last_seen|join_date)$"),
    order: str = Query("desc", regex="^(asc|desc)$"),
    search: Optional[str] = Query(None),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(User).where(User.guild_id == guild_id)
    if search:
        q = q.where(User.username.ilike(f"%{search}%"))

    sort_col = getattr(User, sort, User.message_count)
    q = q.order_by(desc(sort_col) if order == "desc" else sort_col)
    q = q.offset(offset).limit(limit)

    result = await db.execute(q)
    users = result.scalars().all()

    count_q = select(func.count(User.id)).where(User.guild_id == guild_id)
    if search:
        count_q = count_q.where(User.username.ilike(f"%{search}%"))
    total = (await db.execute(count_q)).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "users": [_user_to_dict(u) for u in users],
    }


@router.get("/trust", summary="Trust-Scores aller Benutzer")
async def get_trust_scores(
    guild_id: int = Query(...),
    limit: int = Query(50, le=200),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User.id, User.username, User.trust_score, User.warning_count)
        .where(User.guild_id == guild_id)
        .order_by(User.trust_score.asc())
        .limit(limit)
    )
    rows = result.all()
    return {
        "guild_id": guild_id,
        "users": [{"user_id": r[0], "username": r[1], "trust_score": r[2], "warnings": r[3]} for r in rows],
    }


@router.get("/risk", summary="Risiko-Scores aller Benutzer")
async def get_risk_scores(
    guild_id: int = Query(...),
    min_risk: float = Query(0.0),
    limit: int = Query(50, le=200),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User.id, User.username, User.risk_score, User.trust_score)
        .where(User.guild_id == guild_id, User.risk_score >= min_risk)
        .order_by(User.risk_score.desc())
        .limit(limit)
    )
    rows = result.all()
    return {
        "guild_id": guild_id,
        "users": [{"user_id": r[0], "username": r[1], "risk_score": r[2], "trust_score": r[3]} for r in rows],
    }


@router.get("/{user_id}", summary="Einzelnen Benutzer abfragen")
async def get_user(
    user_id: int,
    guild_id: int = Query(...),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.guild_id == guild_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    recent_ai = await db.execute(
        select(AIAnalysis)
        .where(AIAnalysis.user_id == user_id, AIAnalysis.guild_id == guild_id)
        .order_by(desc(AIAnalysis.created_at))
        .limit(5)
    )
    analyses = recent_ai.scalars().all()

    data = _user_to_dict(user)
    data["recent_ai_analyses"] = [_analysis_to_dict(a) for a in analyses]
    return data


@router.patch("/{user_id}", summary="Benutzerdaten aktualisieren")
async def update_user(
    user_id: int,
    guild_id: int = Query(...),
    body: UserUpdateRequest = None,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")

    result = await db.execute(
        select(User).where(User.id == user_id, User.guild_id == guild_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body:
        if body.notes is not None:
            user.notes = body.notes
        if body.trust_score is not None:
            user.trust_score = max(0.0, min(100.0, body.trust_score))

    await db.flush()
    return _user_to_dict(user)


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "guild_id": u.guild_id,
        "username": u.username,
        "display_name": u.display_name,
        "avatar_url": u.avatar_url,
        "is_bot": u.is_bot,
        "is_banned": u.is_banned,
        "is_muted": u.is_muted,
        "is_perma_muted": u.is_perma_muted,
        "trust_score": u.trust_score,
        "risk_score": u.risk_score,
        "message_count": u.message_count,
        "voice_minutes": u.voice_minutes,
        "warning_count": u.warning_count,
        "timeout_count": u.timeout_count,
        "first_seen": u.first_seen.isoformat() if u.first_seen else None,
        "last_seen": u.last_seen.isoformat() if u.last_seen else None,
        "join_date": u.join_date.isoformat() if u.join_date else None,
        "notes": u.notes,
    }


def _analysis_to_dict(a: AIAnalysis) -> dict:
    return {
        "id": a.id,
        "risk_score": a.risk_score,
        "severity": a.severity,
        "flags": a.flags,
        "reasoning": a.reasoning,
        "recommended_action": a.recommended_action,
        "action_taken": a.action_taken,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
