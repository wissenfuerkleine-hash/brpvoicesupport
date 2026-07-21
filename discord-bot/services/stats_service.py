"""
Statistics Service
Aggregates and stores server statistics.
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from database.models import Message, VoiceSession, Warning, Timeout, Ban, AIAnalysis, ServerStats, User, Channel
from utils.logger import logger


async def record_message(
    db: AsyncSession,
    guild_id: int,
    user_id: int,
    channel_id: int,
    message_id: int,
    content: str,
    attachment_count: int = 0,
    mention_count: int = 0,
    created_at: datetime = None,
) -> None:
    import hashlib
    if created_at is None:
        created_at = datetime.now(timezone.utc)

    content_hash = hashlib.sha256(content.encode()).hexdigest() if content else None
    msg = Message(
        id=message_id,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        content=content[:4000] if content else None,
        content_hash=content_hash,
        attachment_count=attachment_count,
        mention_count=mention_count,
        created_at=created_at,
    )
    db.add(msg)

    await db.execute(
        update(User)
        .where(User.id == user_id, User.guild_id == guild_id)
        .values(message_count=User.message_count + 1, last_seen=datetime.now(timezone.utc))
    )
    await db.execute(
        update(Channel)
        .where(Channel.id == channel_id, Channel.guild_id == guild_id)
        .values(message_count=Channel.message_count + 1)
    )
    await db.flush()


async def record_message_delete(db: AsyncSession, message_id: int, guild_id: int) -> None:
    await db.execute(
        update(Message)
        .where(Message.id == message_id, Message.guild_id == guild_id)
        .values(is_deleted=True, deleted_at=datetime.now(timezone.utc))
    )
    await db.flush()


async def record_message_edit(db: AsyncSession, message_id: int, guild_id: int, new_content: str) -> None:
    await db.execute(
        update(Message)
        .where(Message.id == message_id, Message.guild_id == guild_id)
        .values(is_edited=True, edited_at=datetime.now(timezone.utc), content=new_content[:4000])
    )
    await db.flush()


async def start_voice_session(
    db: AsyncSession,
    guild_id: int,
    user_id: int,
    channel_id: int,
    channel_name: str,
) -> VoiceSession:
    session = VoiceSession(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        channel_name=channel_name,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.flush()
    return session


async def end_voice_session(
    db: AsyncSession,
    guild_id: int,
    user_id: int,
) -> None:
    result = await db.execute(
        select(VoiceSession)
        .where(
            VoiceSession.guild_id == guild_id,
            VoiceSession.user_id == user_id,
            VoiceSession.left_at.is_(None),
        )
        .order_by(VoiceSession.joined_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if not session:
        return
    now = datetime.now(timezone.utc)
    duration = int((now - session.joined_at).total_seconds())
    session.left_at = now
    session.duration_seconds = duration

    await db.execute(
        update(User)
        .where(User.id == user_id, User.guild_id == guild_id)
        .values(voice_minutes=User.voice_minutes + duration // 60)
    )
    await db.flush()


async def get_server_stats_summary(db: AsyncSession, guild_id: int) -> dict:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    msg_24h = await db.execute(
        select(func.count(Message.id)).where(
            Message.guild_id == guild_id,
            Message.created_at >= day_ago,
        )
    )
    msg_7d = await db.execute(
        select(func.count(Message.id)).where(
            Message.guild_id == guild_id,
            Message.created_at >= week_ago,
        )
    )
    total_users = await db.execute(
        select(func.count(User.id)).where(User.guild_id == guild_id)
    )
    active_users_24h = await db.execute(
        select(func.count(User.id)).where(
            User.guild_id == guild_id,
            User.last_seen >= day_ago,
        )
    )
    warn_count = await db.execute(
        select(func.count(Warning.id)).where(Warning.guild_id == guild_id)
    )
    timeout_count = await db.execute(
        select(func.count(Timeout.id)).where(Timeout.guild_id == guild_id)
    )
    ban_count = await db.execute(
        select(func.count(Ban.id)).where(Ban.guild_id == guild_id)
    )
    ai_flags = await db.execute(
        select(func.count(AIAnalysis.id)).where(
            AIAnalysis.guild_id == guild_id,
            AIAnalysis.severity > 0,
        )
    )

    top_users_result = await db.execute(
        select(User.username, User.message_count)
        .where(User.guild_id == guild_id)
        .order_by(User.message_count.desc())
        .limit(10)
    )
    top_channels_result = await db.execute(
        select(Channel.name, Channel.message_count)
        .where(Channel.guild_id == guild_id)
        .order_by(Channel.message_count.desc())
        .limit(10)
    )

    return {
        "messages_24h": msg_24h.scalar() or 0,
        "messages_7d": msg_7d.scalar() or 0,
        "total_users": total_users.scalar() or 0,
        "active_users_24h": active_users_24h.scalar() or 0,
        "warnings_total": warn_count.scalar() or 0,
        "timeouts_total": timeout_count.scalar() or 0,
        "bans_total": ban_count.scalar() or 0,
        "ai_flags_total": ai_flags.scalar() or 0,
        "top_users": [{"username": r[0], "messages": r[1]} for r in top_users_result.all()],
        "top_channels": [{"name": r[0], "messages": r[1]} for r in top_channels_result.all()],
    }
