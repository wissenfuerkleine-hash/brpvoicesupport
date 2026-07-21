"""
Statistics routes: GET /stats, GET /activity, GET /voice, GET /server, GET /channels
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import Optional
from datetime import datetime, timezone, timedelta
from database.connection import get_db
from database.models import (
    Guild, Channel, User, Message, VoiceSession,
    AIAnalysis, Warning, Timeout, Ban, AuditLog
)
from services.stats_service import get_server_stats_summary
from api.middleware.auth import get_current_user, TokenData

router = APIRouter(tags=["Statistics"])


@router.get("/dashboard", summary="Dashboard-Übersicht für Bubble")
async def get_dashboard(
    guild_id: int = Query(...),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stats = await get_server_stats_summary(db, guild_id)

    guild_r = await db.execute(select(Guild).where(Guild.id == guild_id))
    guild = guild_r.scalar_one_or_none()

    recent_logs = await db.execute(
        select(AuditLog)
        .where(AuditLog.guild_id == guild_id)
        .order_by(desc(AuditLog.created_at))
        .limit(10)
    )
    logs = recent_logs.scalars().all()

    high_risk_users = await db.execute(
        select(User)
        .where(User.guild_id == guild_id, User.risk_score >= 50)
        .order_by(desc(User.risk_score))
        .limit(10)
    )
    risky = high_risk_users.scalars().all()

    return {
        "guild": {
            "id": guild.id if guild else guild_id,
            "name": guild.name if guild else "Unknown",
            "member_count": guild.member_count if guild else 0,
        },
        "stats": stats,
        "recent_actions": [
            {
                "action": l.action,
                "user": l.username,
                "timestamp": l.created_at.isoformat(),
                "severity": l.severity,
            }
            for l in logs
        ],
        "high_risk_users": [
            {
                "user_id": u.id,
                "username": u.username,
                "risk_score": u.risk_score,
                "trust_score": u.trust_score,
                "warnings": u.warning_count,
            }
            for u in risky
        ],
    }


@router.get("/stats", summary="Serverstatistiken")
async def get_stats(
    guild_id: int = Query(...),
    period: str = Query("24h", regex="^(1h|24h|7d|30d)$"),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    period_map = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
    since = now - period_map[period]

    msg_count = (await db.execute(
        select(func.count(Message.id)).where(Message.guild_id == guild_id, Message.created_at >= since)
    )).scalar() or 0

    active_users = (await db.execute(
        select(func.count(func.distinct(Message.user_id))).where(Message.guild_id == guild_id, Message.created_at >= since)
    )).scalar() or 0

    ai_flags = (await db.execute(
        select(func.count(AIAnalysis.id)).where(AIAnalysis.guild_id == guild_id, AIAnalysis.created_at >= since, AIAnalysis.severity > 0)
    )).scalar() or 0

    warnings = (await db.execute(
        select(func.count(Warning.id)).where(Warning.guild_id == guild_id, Warning.created_at >= since)
    )).scalar() or 0

    timeouts = (await db.execute(
        select(func.count(Timeout.id)).where(Timeout.guild_id == guild_id, Timeout.created_at >= since)
    )).scalar() or 0

    bans = (await db.execute(
        select(func.count(Ban.id)).where(Ban.guild_id == guild_id, Ban.created_at >= since)
    )).scalar() or 0

    return {
        "guild_id": guild_id,
        "period": period,
        "since": since.isoformat(),
        "messages": msg_count,
        "active_users": active_users,
        "ai_flags": ai_flags,
        "warnings": warnings,
        "timeouts": timeouts,
        "bans": bans,
    }


@router.get("/server", summary="Serverinformationen")
async def get_server(
    guild_id: int = Query(...),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Guild).where(Guild.id == guild_id))
    guild = result.scalar_one_or_none()
    if not guild:
        return {"error": "Guild not found"}

    total_users = (await db.execute(select(func.count(User.id)).where(User.guild_id == guild_id))).scalar() or 0
    total_channels = (await db.execute(select(func.count(Channel.id)).where(Channel.guild_id == guild_id))).scalar() or 0

    return {
        "id": guild.id,
        "name": guild.name,
        "icon_url": guild.icon_url,
        "owner_id": guild.owner_id,
        "member_count": guild.member_count,
        "total_users_tracked": total_users,
        "total_channels_tracked": total_channels,
        "joined_at": guild.joined_at.isoformat() if guild.joined_at else None,
        "is_active": guild.is_active,
        "settings": guild.settings,
    }


@router.get("/channels", summary="Kanalstatistiken")
async def get_channels(
    guild_id: int = Query(...),
    limit: int = Query(50, le=200),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Channel)
        .where(Channel.guild_id == guild_id)
        .order_by(desc(Channel.message_count))
        .limit(limit)
    )
    channels = result.scalars().all()
    return {
        "guild_id": guild_id,
        "channels": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.channel_type,
                "category": c.category_name,
                "message_count": c.message_count,
                "is_nsfw": c.is_nsfw,
                "is_monitored": c.is_monitored,
            }
            for c in channels
        ],
    }


@router.get("/voice", summary="Voice-Statistiken")
async def get_voice_stats(
    guild_id: int = Query(...),
    limit: int = Query(50, le=200),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    top_voice = await db.execute(
        select(User.id, User.username, User.voice_minutes)
        .where(User.guild_id == guild_id, User.voice_minutes > 0)
        .order_by(desc(User.voice_minutes))
        .limit(limit)
    )
    rows = top_voice.all()

    recent_sessions = await db.execute(
        select(VoiceSession)
        .where(VoiceSession.guild_id == guild_id)
        .order_by(desc(VoiceSession.joined_at))
        .limit(20)
    )
    sessions = recent_sessions.scalars().all()

    return {
        "guild_id": guild_id,
        "top_voice_users": [
            {"user_id": r[0], "username": r[1], "voice_minutes": r[2]} for r in rows
        ],
        "recent_sessions": [
            {
                "user_id": s.user_id,
                "channel": s.channel_name,
                "joined_at": s.joined_at.isoformat(),
                "duration_seconds": s.duration_seconds,
                "active": s.left_at is None,
            }
            for s in sessions
        ],
    }


@router.get("/activity", summary="Aktivitätsdaten für Heatmap/Charts")
async def get_activity(
    guild_id: int = Query(...),
    days: int = Query(7, le=30),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date_trunc("hour", Message.created_at).label("hour"),
            func.count(Message.id).label("count"),
        )
        .where(Message.guild_id == guild_id, Message.created_at >= since)
        .group_by("hour")
        .order_by("hour")
    )
    rows = result.all()

    joins_result = await db.execute(
        select(
            func.date(AuditLog.created_at).label("day"),
            func.count(AuditLog.id).label("joins"),
        )
        .where(AuditLog.guild_id == guild_id, AuditLog.action == "member_join", AuditLog.created_at >= since)
        .group_by("day")
        .order_by("day")
    )
    join_rows = joins_result.all()

    return {
        "guild_id": guild_id,
        "period_days": days,
        "message_heatmap": [
            {"hour": str(r[0]), "messages": r[1]} for r in rows
        ],
        "daily_joins": [
            {"day": str(r[0]), "joins": r[1]} for r in join_rows
        ],
    }


@router.post("/settings", summary="Server-Einstellungen über API aktualisieren")
async def update_settings(
    guild_id: int = Query(...),
    body: dict = None,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from database.models import DashboardSettings
    from sqlalchemy import update as sql_update

    result = await db.execute(
        select(DashboardSettings).where(DashboardSettings.guild_id == guild_id)
    )
    s = result.scalar_one_or_none()

    if not s:
        s = DashboardSettings(guild_id=guild_id)
        db.add(s)

    if body:
        allowed_fields = [
            "auto_moderation", "raid_protection", "spam_protection", "link_filter",
            "invite_filter", "caps_filter", "mention_limit", "message_rate_limit",
            "message_rate_window", "min_account_age_days", "warn_threshold",
            "timeout_threshold", "perma_mute_threshold", "log_channel_id",
            "alert_channel_id", "mod_channel_id",
        ]
        for field in allowed_fields:
            if field in body:
                setattr(s, field, body[field])

    await db.flush()
    return {"success": True, "guild_id": guild_id}
