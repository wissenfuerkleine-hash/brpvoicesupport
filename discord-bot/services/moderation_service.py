"""
Moderation Service
Executes moderation actions on Discord members and persists records.
"""

import discord
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from database.models import User, Warning, Timeout, Ban, AuditLog, Guild, DashboardSettings
from services.trust_service import apply_moderation_action, apply_ai_trust_impact, get_trust_score
from utils.logger import logger
from config.settings import settings


# Timeout durations
TIMEOUT_SHORT = 10 * 60        # 10 minutes
TIMEOUT_LONG = 60 * 60         # 1 hour


async def _ensure_user(db: AsyncSession, member: discord.Member) -> User:
    """Upsert a User record from a Discord Member."""
    result = await db.execute(
        select(User).where(User.id == member.id, User.guild_id == member.guild.id)
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            id=member.id,
            guild_id=member.guild.id,
            username=str(member),
            discriminator=member.discriminator,
            display_name=member.display_name,
            avatar_url=str(member.display_avatar.url) if member.display_avatar else None,
            is_bot=member.bot,
            join_date=member.joined_at,
            trust_score=100.0,
            risk_score=0.0,
        )
        db.add(user)
        await db.flush()
    return user


async def _get_guild_settings(db: AsyncSession, guild_id: int) -> DashboardSettings | None:
    result = await db.execute(
        select(DashboardSettings).where(DashboardSettings.guild_id == guild_id)
    )
    return result.scalar_one_or_none()


async def _log_action(
    db: AsyncSession,
    guild_id: int,
    user: discord.Member | None,
    moderator: discord.Member | None,
    action: str,
    reason: str,
    risk_score: float = 0.0,
    trust_score: float = 100.0,
    severity: int = 0,
    ai_reasoning: str = "",
    extra: dict = None,
    channel: discord.TextChannel = None,
    message: discord.Message = None,
):
    log = AuditLog(
        guild_id=guild_id,
        user_id=user.id if user else None,
        username=str(user) if user else None,
        moderator_id=moderator.id if moderator else None,
        moderator_name=str(moderator) if moderator else None,
        action=action,
        channel_id=channel.id if channel else None,
        channel_name=channel.name if channel else None,
        message_id=message.id if message else None,
        message_content=(message.content[:2000] if message and message.content else None),
        risk_score=risk_score,
        trust_score=trust_score,
        severity=severity,
        ai_reasoning=ai_reasoning,
        extra_data=extra or {},
    )
    db.add(log)
    await db.flush()


async def execute_moderation(
    db: AsyncSession,
    guild: discord.Guild,
    member: discord.Member,
    severity: int,
    reason: str,
    risk_score: float,
    ai_reasoning: str,
    message: discord.Message = None,
    moderator: discord.Member = None,
) -> str:
    """
    Execute the appropriate moderation action based on severity.
    Returns a description of what was done.
    """
    if member.bot:
        return "skipped:bot"

    # Check whitelist
    whitelist_role = discord.utils.get(member.roles, id=settings.whitelist_role_id)
    if whitelist_role:
        return "skipped:whitelisted"

    # Check admin role
    admin_role = discord.utils.get(member.roles, id=settings.admin_role_id)
    if admin_role:
        return "skipped:admin"

    user_db = await _ensure_user(db, member)
    trust = await get_trust_score(db, member.id, guild.id)
    action_taken = "none"

    if severity == 0:
        action_taken = "none"

    elif severity == 1:
        # Warn
        warning = Warning(
            guild_id=guild.id,
            user_id=member.id,
            reason=reason,
            ai_generated=True,
            risk_score=risk_score,
        )
        db.add(warning)
        user_db.warning_count = (user_db.warning_count or 0) + 1
        await apply_moderation_action(db, member.id, guild.id, "warn")
        action_taken = "warn"

        try:
            await member.send(
                f"⚠️ **Verwarnung** auf **{guild.name}**\nGrund: {reason}"
            )
        except discord.Forbidden:
            pass

    elif severity == 2:
        # Delete + 10 min timeout
        if message:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass

        try:
            await member.timeout(
                timedelta(seconds=TIMEOUT_SHORT),
                reason=f"[AI Mod] {reason}"
            )
        except discord.Forbidden:
            logger.warning("Cannot timeout %s – missing permissions", member)

        timeout_record = Timeout(
            guild_id=guild.id,
            user_id=member.id,
            duration_seconds=TIMEOUT_SHORT,
            reason=reason,
            ai_generated=True,
            risk_score=risk_score,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=TIMEOUT_SHORT),
            is_active=True,
        )
        db.add(timeout_record)
        user_db.timeout_count = (user_db.timeout_count or 0) + 1
        await apply_moderation_action(db, member.id, guild.id, "timeout")
        action_taken = "delete_timeout"

        try:
            await member.send(
                f"🔇 **Timeout (10 Min)** auf **{guild.name}**\nGrund: {reason}"
            )
        except discord.Forbidden:
            pass

    elif severity == 3:
        # 1-hour timeout + log + notify
        if message:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass

        try:
            await member.timeout(
                timedelta(seconds=TIMEOUT_LONG),
                reason=f"[AI Mod - Severe] {reason}"
            )
        except discord.Forbidden:
            logger.warning("Cannot timeout %s – missing permissions", member)

        timeout_record = Timeout(
            guild_id=guild.id,
            user_id=member.id,
            duration_seconds=TIMEOUT_LONG,
            reason=reason,
            ai_generated=True,
            risk_score=risk_score,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=TIMEOUT_LONG),
            is_active=True,
        )
        db.add(timeout_record)
        user_db.timeout_count = (user_db.timeout_count or 0) + 1
        await apply_moderation_action(db, member.id, guild.id, "long_timeout")
        action_taken = "long_timeout"

        await _notify_mods(guild, member, reason, risk_score, ai_reasoning, severity)

        try:
            await member.send(
                f"🔇 **Timeout (1 Std)** auf **{guild.name}**\nGrund: {reason}\n"
                f"Ein Moderator wurde benachrichtigt."
            )
        except discord.Forbidden:
            pass

    elif severity >= 4:
        # Perma mute: remove all roles with send_messages, add muted role if exists
        if message:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound):
                pass

        # Discord's timeout API max is 28 days; for perma mute we use max duration
        try:
            await member.timeout(
                timedelta(days=28),
                reason=f"[AI Mod - PERMA MUTE] {reason} — Bitte Admin kontaktieren"
            )
        except discord.Forbidden:
            logger.warning("Cannot perma mute %s – missing permissions", member)

        timeout_record = Timeout(
            guild_id=guild.id,
            user_id=member.id,
            duration_seconds=28 * 24 * 3600,
            reason=f"PERMA MUTE: {reason}",
            ai_generated=True,
            risk_score=risk_score,
            expires_at=datetime.now(timezone.utc) + timedelta(days=28),
            is_active=True,
        )
        db.add(timeout_record)
        user_db.is_perma_muted = True
        user_db.timeout_count = (user_db.timeout_count or 0) + 1
        await apply_moderation_action(db, member.id, guild.id, "perma_mute")
        action_taken = "perma_mute"

        await _notify_admins(guild, member, reason, risk_score, ai_reasoning)

        try:
            await member.send(
                f"🚫 **Permanent gemutet** auf **{guild.name}**\n"
                f"Grund: {reason}\n"
                f"Ein Administrator wurde benachrichtigt und wird deinen Fall prüfen."
            )
        except discord.Forbidden:
            pass

    user_db.risk_score = risk_score
    await _log_action(
        db, guild.id, member, moderator, action_taken,
        reason, risk_score, trust, severity, ai_reasoning,
        message=message,
        channel=message.channel if message else None,
    )
    await db.flush()
    return action_taken


async def _notify_mods(
    guild: discord.Guild,
    member: discord.Member,
    reason: str,
    risk_score: float,
    ai_reasoning: str,
    severity: int,
):
    log_channel_id = settings.log_channel_id or settings.alert_channel_id
    if not log_channel_id:
        return
    channel = guild.get_channel(log_channel_id)
    if not channel:
        return
    embed = discord.Embed(
        title="⚠️ Moderator-Benachrichtigung",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Benutzer", value=f"{member} ({member.id})", inline=True)
    embed.add_field(name="Schweregrad", value=str(severity), inline=True)
    embed.add_field(name="Risiko-Score", value=f"{risk_score:.1f}/100", inline=True)
    embed.add_field(name="Grund", value=reason[:1024], inline=False)
    embed.add_field(name="KI-Begründung", value=(ai_reasoning[:1024] or "–"), inline=False)
    try:
        await channel.send(embed=embed)
    except Exception as e:
        logger.error("Failed to send mod notification: %s", e)


async def _notify_admins(
    guild: discord.Guild,
    member: discord.Member,
    reason: str,
    risk_score: float,
    ai_reasoning: str,
):
    alert_channel_id = settings.alert_channel_id or settings.log_channel_id
    if not alert_channel_id:
        return
    channel = guild.get_channel(alert_channel_id)
    if not channel:
        return

    admin_role = discord.utils.get(guild.roles, id=settings.admin_role_id)
    mention = admin_role.mention if admin_role else "@Admin"

    embed = discord.Embed(
        title="🚫 ADMIN-AKTION ERFORDERLICH — Permanent Mute",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Benutzer", value=f"{member.mention} ({member.id})", inline=True)
    embed.add_field(name="Risiko-Score", value=f"{risk_score:.1f}/100", inline=True)
    embed.add_field(name="Grund", value=reason[:1024], inline=False)
    embed.add_field(name="KI-Begründung", value=(ai_reasoning[:1024] or "–"), inline=False)
    embed.set_footer(text="Bitte prüfen und entsprechend handeln.")
    try:
        await channel.send(content=mention, embed=embed)
    except Exception as e:
        logger.error("Failed to send admin notification: %s", e)


async def issue_manual_warning(
    db: AsyncSession,
    guild: discord.Guild,
    member: discord.Member,
    moderator: discord.Member,
    reason: str,
) -> Warning:
    user_db = await _ensure_user(db, member)
    warning = Warning(
        guild_id=guild.id,
        user_id=member.id,
        moderator_id=moderator.id,
        reason=reason,
        ai_generated=False,
        risk_score=0.0,
    )
    db.add(warning)
    user_db.warning_count = (user_db.warning_count or 0) + 1
    await apply_moderation_action(db, member.id, guild.id, "warn")
    await _log_action(db, guild.id, member, moderator, "manual_warn", reason)
    await db.flush()
    return warning


async def remove_warning(
    db: AsyncSession,
    warning_id: int,
    guild_id: int,
    moderator_id: int,
) -> bool:
    result = await db.execute(
        select(Warning).where(Warning.id == warning_id, Warning.guild_id == guild_id)
    )
    warning = result.scalar_one_or_none()
    if not warning:
        return False
    warning.is_active = False
    await db.flush()
    return True


async def issue_manual_timeout(
    db: AsyncSession,
    guild: discord.Guild,
    member: discord.Member,
    moderator: discord.Member,
    duration_seconds: int,
    reason: str,
) -> Timeout:
    user_db = await _ensure_user(db, member)
    try:
        await member.timeout(timedelta(seconds=duration_seconds), reason=f"[Manual] {reason}")
    except discord.Forbidden:
        pass

    record = Timeout(
        guild_id=guild.id,
        user_id=member.id,
        moderator_id=moderator.id,
        duration_seconds=duration_seconds,
        reason=reason,
        ai_generated=False,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=duration_seconds),
        is_active=True,
    )
    db.add(record)
    user_db.timeout_count = (user_db.timeout_count or 0) + 1
    await apply_moderation_action(db, member.id, guild.id, "timeout")
    await _log_action(db, guild.id, member, moderator, "manual_timeout", reason, extra={"duration": duration_seconds})
    await db.flush()
    return record


async def issue_manual_ban(
    db: AsyncSession,
    guild: discord.Guild,
    member: discord.Member,
    moderator: discord.Member,
    reason: str,
) -> Ban:
    user_db = await _ensure_user(db, member)
    try:
        await guild.ban(member, reason=f"[Manual] {reason}", delete_message_days=1)
    except discord.Forbidden:
        pass

    ban = Ban(
        guild_id=guild.id,
        user_id=member.id,
        moderator_id=moderator.id,
        reason=reason,
        is_active=True,
    )
    db.add(ban)
    user_db.is_banned = True
    await _log_action(db, guild.id, member, moderator, "manual_ban", reason)
    await db.flush()
    return ban


async def issue_unban(
    db: AsyncSession,
    guild: discord.Guild,
    user_id: int,
    moderator: discord.Member,
    reason: str,
) -> bool:
    try:
        ban_entry = await guild.fetch_ban(discord.Object(id=user_id))
        await guild.unban(ban_entry.user, reason=reason)
    except (discord.NotFound, discord.Forbidden):
        return False

    result = await db.execute(
        select(Ban).where(Ban.guild_id == guild.id, Ban.user_id == user_id, Ban.is_active == True)
    )
    ban = result.scalar_one_or_none()
    if ban:
        ban.is_active = False
        ban.unbanned_at = datetime.now(timezone.utc)
        ban.unban_reason = reason

    await db.flush()
    return True
