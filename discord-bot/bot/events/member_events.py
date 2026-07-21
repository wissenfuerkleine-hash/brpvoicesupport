"""
Member event handlers: joins, leaves, role changes, nickname changes
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
from sqlalchemy import select, update
from database.connection import AsyncSessionLocal
from database.models import User, Guild, AuditLog, DashboardSettings
from ai.moderation_engine import analyze_join_event
from services.moderation_service import execute_moderation, _ensure_user
from utils.helpers import account_age_days, is_protected
from utils.logger import logger


class MemberEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(select(Guild).where(Guild.id == member.guild.id))
                guild_db = result.scalar_one_or_none()
                if guild_db:
                    guild_db.member_count = member.guild.member_count

                user = User(
                    id=member.id,
                    guild_id=member.guild.id,
                    username=str(member),
                    discriminator=member.discriminator,
                    display_name=member.display_name,
                    avatar_url=str(member.display_avatar.url) if member.display_avatar else None,
                    is_bot=member.bot,
                    join_date=member.joined_at or datetime.now(timezone.utc),
                    trust_score=100.0,
                    risk_score=0.0,
                )
                result_existing = await db.execute(
                    select(User).where(User.id == member.id, User.guild_id == member.guild.id)
                )
                existing = result_existing.scalar_one_or_none()
                if existing:
                    existing.join_date = member.joined_at or datetime.now(timezone.utc)
                    existing.leave_date = None
                else:
                    db.add(user)

                await db.flush()

                if not member.bot:
                    acc_age = account_age_days(member.created_at)
                    analysis = analyze_join_event(
                        guild_id=member.guild.id,
                        account_age_days=acc_age,
                        join_history=[],
                    )

                    if analysis.severity >= 2 and not is_protected(member):
                        await execute_moderation(
                            db=db,
                            guild=member.guild,
                            member=member,
                            severity=analysis.severity,
                            reason=f"[Join-Analyse] {analysis.reasoning}",
                            risk_score=analysis.risk_score,
                            ai_reasoning=analysis.reasoning,
                        )

                    log = AuditLog(
                        guild_id=member.guild.id,
                        user_id=member.id,
                        username=str(member),
                        action="member_join",
                        risk_score=analysis.risk_score,
                        ai_reasoning=analysis.reasoning,
                        extra_data={"account_age_days": acc_age, "flags": analysis.flags},
                    )
                    db.add(log)

                await db.commit()
                logger.info("[JOIN] %s joined %s", member, member.guild.name)
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_member_join: %s", e, exc_info=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    update(User)
                    .where(User.id == member.id, User.guild_id == member.guild.id)
                    .values(leave_date=datetime.now(timezone.utc))
                )
                result = await db.execute(select(Guild).where(Guild.id == member.guild.id))
                guild_db = result.scalar_one_or_none()
                if guild_db:
                    guild_db.member_count = member.guild.member_count

                log = AuditLog(
                    guild_id=member.guild.id,
                    user_id=member.id,
                    username=str(member),
                    action="member_leave",
                    extra_data={"roles": [r.name for r in member.roles if r.name != "@everyone"]},
                )
                db.add(log)
                await db.commit()
                logger.info("[LEAVE] %s left %s", member, member.guild.name)
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_member_remove: %s", e, exc_info=True)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        async with AsyncSessionLocal() as db:
            try:
                changes = {}

                if before.roles != after.roles:
                    added = [r.id for r in after.roles if r not in before.roles]
                    removed = [r.id for r in before.roles if r not in after.roles]
                    changes["roles_added"] = added
                    changes["roles_removed"] = removed

                if before.nick != after.nick:
                    changes["nick_before"] = before.nick
                    changes["nick_after"] = after.nick

                if before.display_avatar != after.display_avatar:
                    changes["avatar_changed"] = True

                if changes:
                    await db.execute(
                        update(User)
                        .where(User.id == after.id, User.guild_id == after.guild.id)
                        .values(
                            display_name=after.display_name,
                            roles=[r.id for r in after.roles],
                        )
                    )
                    log = AuditLog(
                        guild_id=after.guild.id,
                        user_id=after.id,
                        username=str(after),
                        action="member_update",
                        extra_data=changes,
                    )
                    db.add(log)
                    await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_member_update: %s", e, exc_info=True)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        if before.name != after.name or before.discriminator != after.discriminator:
            async with AsyncSessionLocal() as db:
                try:
                    await db.execute(
                        update(User)
                        .where(User.id == after.id)
                        .values(username=str(after), discriminator=after.discriminator)
                    )
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.error("Error in on_user_update: %s", e, exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MemberEvents(bot))
