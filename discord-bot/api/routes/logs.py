"""
Log routes: GET /logs, GET /warnings, GET /timeouts, POST /warnings, DELETE /warning
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, update
from typing import Optional
from pydantic import BaseModel
from datetime import datetime
from database.connection import get_db
from database.models import AuditLog, Warning, Timeout, Ban
from api.middleware.auth import get_current_user, TokenData, require_admin
from utils.logger import logger

router = APIRouter(tags=["Logs & Moderation"])


# --- Audit Logs ---

@router.get("/logs", summary="Audit-Logs abrufen")
async def get_logs(
    guild_id: int = Query(...),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog).where(AuditLog.guild_id == guild_id)
    if action:
        q = q.where(AuditLog.action == action)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    q = q.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)

    result = await db.execute(q)
    logs = result.scalars().all()

    count_q = select(func.count(AuditLog.id)).where(AuditLog.guild_id == guild_id)
    total = (await db.execute(count_q)).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [_log_to_dict(l) for l in logs],
    }


# --- Warnings ---

@router.get("/warnings", summary="Verwarnungen abrufen")
async def get_warnings(
    guild_id: int = Query(...),
    user_id: Optional[int] = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Warning).where(Warning.guild_id == guild_id)
    if user_id:
        q = q.where(Warning.user_id == user_id)
    if active_only:
        q = q.where(Warning.is_active == True)
    q = q.order_by(desc(Warning.created_at)).offset(offset).limit(limit)

    result = await db.execute(q)
    warnings = result.scalars().all()
    total = (await db.execute(select(func.count(Warning.id)).where(Warning.guild_id == guild_id))).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "warnings": [_warning_to_dict(w) for w in warnings],
    }


class WarningCreate(BaseModel):
    guild_id: int
    user_id: int
    reason: str
    moderator_id: Optional[int] = None


@router.post("/warnings", summary="Manuelle Verwarnung erstellen")
async def create_warning(
    body: WarningCreate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")

    warning = Warning(
        guild_id=body.guild_id,
        user_id=body.user_id,
        moderator_id=body.moderator_id or current_user.user_id,
        reason=body.reason,
        ai_generated=False,
    )
    db.add(warning)
    await db.flush()
    return _warning_to_dict(warning)


@router.delete("/warnings/{warning_id}", summary="Verwarnung deaktivieren")
async def delete_warning(
    warning_id: int,
    guild_id: int = Query(...),
    current_user: TokenData = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Warning).where(Warning.id == warning_id, Warning.guild_id == guild_id)
    )
    warning = result.scalar_one_or_none()
    if not warning:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Warning not found")
    warning.is_active = False
    await db.flush()
    return {"success": True, "warning_id": warning_id}


# --- Timeouts ---

@router.get("/timeouts", summary="Timeouts abrufen")
async def get_timeouts(
    guild_id: int = Query(...),
    user_id: Optional[int] = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Timeout).where(Timeout.guild_id == guild_id)
    if user_id:
        q = q.where(Timeout.user_id == user_id)
    if active_only:
        q = q.where(Timeout.is_active == True)
    q = q.order_by(desc(Timeout.created_at)).offset(offset).limit(limit)

    result = await db.execute(q)
    timeouts = result.scalars().all()
    total = (await db.execute(select(func.count(Timeout.id)).where(Timeout.guild_id == guild_id))).scalar() or 0

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "timeouts": [_timeout_to_dict(t) for t in timeouts],
    }


class TimeoutCreate(BaseModel):
    guild_id: int
    user_id: int
    duration_seconds: int
    reason: str


@router.post("/timeouts", summary="Timeout über API setzen")
async def create_timeout(
    body: TimeoutCreate,
    current_user: TokenData = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timezone, timedelta
    record = Timeout(
        guild_id=body.guild_id,
        user_id=body.user_id,
        moderator_id=current_user.user_id,
        duration_seconds=body.duration_seconds,
        reason=body.reason,
        ai_generated=False,
        is_active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=body.duration_seconds),
    )
    db.add(record)
    await db.flush()
    return _timeout_to_dict(record)


# --- Bans ---

class BanCreate(BaseModel):
    guild_id: int
    user_id: int
    reason: str


@router.post("/ban", summary="Ban via API")
async def create_ban(
    body: BanCreate,
    current_user: TokenData = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    ban = Ban(
        guild_id=body.guild_id,
        user_id=body.user_id,
        moderator_id=current_user.user_id,
        reason=body.reason,
        is_active=True,
    )
    db.add(ban)
    await db.flush()
    return {"success": True, "ban_id": ban.id}


class UnbanRequest(BaseModel):
    guild_id: int
    user_id: int
    reason: str


@router.post("/unban", summary="Unban via API")
async def api_unban(
    body: UnbanRequest,
    current_user: TokenData = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone
    result = await db.execute(
        select(Ban).where(Ban.guild_id == body.guild_id, Ban.user_id == body.user_id, Ban.is_active == True)
    )
    ban = result.scalar_one_or_none()
    if ban:
        ban.is_active = False
        ban.unbanned_at = datetime.now(timezone.utc)
        ban.unban_reason = body.reason
    await db.flush()
    return {"success": True, "message": f"User {body.user_id} unbanned"}


# --- Helpers ---

def _log_to_dict(l: AuditLog) -> dict:
    return {
        "id": l.id,
        "guild_id": l.guild_id,
        "user_id": l.user_id,
        "username": l.username,
        "moderator_id": l.moderator_id,
        "moderator_name": l.moderator_name,
        "action": l.action,
        "channel_id": l.channel_id,
        "channel_name": l.channel_name,
        "message_id": l.message_id,
        "message_content": l.message_content,
        "risk_score": l.risk_score,
        "trust_score": l.trust_score,
        "severity": l.severity,
        "ai_reasoning": l.ai_reasoning,
        "extra_data": l.extra_data,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }


def _warning_to_dict(w: Warning) -> dict:
    return {
        "id": w.id,
        "guild_id": w.guild_id,
        "user_id": w.user_id,
        "moderator_id": w.moderator_id,
        "reason": w.reason,
        "ai_generated": w.ai_generated,
        "risk_score": w.risk_score,
        "is_active": w.is_active,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


def _timeout_to_dict(t: Timeout) -> dict:
    return {
        "id": t.id,
        "guild_id": t.guild_id,
        "user_id": t.user_id,
        "moderator_id": t.moderator_id,
        "duration_seconds": t.duration_seconds,
        "reason": t.reason,
        "ai_generated": t.ai_generated,
        "is_active": t.is_active,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
    }
