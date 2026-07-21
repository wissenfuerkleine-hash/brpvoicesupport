"""
Trust Score Service
Manages dynamic trust scores per user per guild.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.models import User
from utils.logger import logger


TRUST_MIN = 0.0
TRUST_MAX = 100.0
TRUST_DEFAULT = 100.0

TRUST_GAIN_GOOD_MESSAGE = 0.05
TRUST_GAIN_VOICE_PER_HOUR = 0.5

TRUST_LOSS_WARN = 10.0
TRUST_LOSS_TIMEOUT = 15.0
TRUST_LOSS_PERMA_MUTE = 30.0
TRUST_LOSS_SPAM = 5.0
TRUST_LOSS_TOXIC = 8.0
TRUST_LOSS_SCAM = 20.0
TRUST_LOSS_RAID = 40.0


def clamp_trust(value: float) -> float:
    return max(TRUST_MIN, min(TRUST_MAX, value))


async def get_trust_score(db: AsyncSession, user_id: int, guild_id: int) -> float:
    result = await db.execute(
        select(User.trust_score).where(User.id == user_id, User.guild_id == guild_id)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else TRUST_DEFAULT


async def update_trust_score(
    db: AsyncSession,
    user_id: int,
    guild_id: int,
    delta: float,
    reason: str = "",
) -> float:
    result = await db.execute(
        select(User).where(User.id == user_id, User.guild_id == guild_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return TRUST_DEFAULT

    old = user.trust_score
    new = clamp_trust(old + delta)
    user.trust_score = new
    await db.flush()
    logger.debug(
        "Trust score update: user=%s guild=%s %.2f → %.2f (%+.2f) reason=%s",
        user_id, guild_id, old, new, delta, reason,
    )
    return new


async def apply_ai_trust_impact(
    db: AsyncSession,
    user_id: int,
    guild_id: int,
    trust_impact: float,
    flags: list,
) -> float:
    if trust_impact >= 0 and not flags:
        delta = TRUST_GAIN_GOOD_MESSAGE
    else:
        delta = trust_impact
    return await update_trust_score(db, user_id, guild_id, delta, reason=",".join(flags[:3]))


async def apply_moderation_action(
    db: AsyncSession,
    user_id: int,
    guild_id: int,
    action: str,
) -> float:
    loss_map = {
        "warn": -TRUST_LOSS_WARN,
        "timeout": -TRUST_LOSS_TIMEOUT,
        "long_timeout": -TRUST_LOSS_TIMEOUT * 1.5,
        "perma_mute": -TRUST_LOSS_PERMA_MUTE,
        "ban": -TRUST_LOSS_PERMA_MUTE,
    }
    delta = loss_map.get(action, 0.0)
    if delta == 0.0:
        return await get_trust_score(db, user_id, guild_id)
    return await update_trust_score(db, user_id, guild_id, delta, reason=f"moderation:{action}")


async def passive_trust_gain(
    db: AsyncSession,
    user_id: int,
    guild_id: int,
) -> float:
    return await update_trust_score(
        db, user_id, guild_id, TRUST_GAIN_GOOD_MESSAGE, reason="clean_message"
    )
