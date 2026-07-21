"""
Message event handlers: on_message, on_message_delete, on_message_edit
"""

import discord
from discord.ext import commands
from sqlalchemy.ext.asyncio import AsyncSession
from database.connection import AsyncSessionLocal
from database.models import AIAnalysis, Message, User, Channel, Guild
from ai.moderation_engine import analyze_message
from services.moderation_service import execute_moderation, _ensure_user
from services.trust_service import apply_ai_trust_impact, passive_trust_gain
from services.stats_service import record_message, record_message_delete, record_message_edit
from utils.helpers import is_protected, account_age_days, join_age_days, truncate
from utils.logger import logger
from sqlalchemy import select


class MessageEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        async with AsyncSessionLocal() as db:
            try:
                await self._ensure_guild(db, message.guild)
                await self._ensure_channel(db, message.channel, message.guild)

                member = message.guild.get_member(message.author.id) or message.author

                if is_protected(member):
                    await record_message(
                        db,
                        message.guild.id,
                        message.author.id,
                        message.channel.id,
                        message.id,
                        message.content,
                        len(message.attachments),
                        len(message.mentions),
                        message.created_at,
                    )
                    await db.commit()
                    return

                user_result = await db.execute(
                    select(User).where(User.id == message.author.id, User.guild_id == message.guild.id)
                )
                user_db = user_result.scalar_one_or_none()

                trust_score = user_db.trust_score if user_db else 100.0
                warning_count = user_db.warning_count if user_db else 0
                timeout_count = user_db.timeout_count if user_db else 0
                acc_age = account_age_days(message.author.created_at)
                j_age = join_age_days(member.joined_at) if hasattr(member, "joined_at") else 0

                result = analyze_message(
                    content=message.content,
                    user_id=message.author.id,
                    guild_id=message.guild.id,
                    account_age_days=acc_age,
                    join_age_days=j_age,
                    trust_score=trust_score,
                    warning_count=warning_count,
                    timeout_count=timeout_count,
                )

                await record_message(
                    db,
                    message.guild.id,
                    message.author.id,
                    message.channel.id,
                    message.id,
                    message.content,
                    len(message.attachments),
                    len(message.mentions),
                    message.created_at,
                )

                ai_analysis = AIAnalysis(
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    message_id=message.id,
                    risk_score=result.risk_score,
                    trust_impact=result.trust_impact,
                    severity=result.severity,
                    flags=result.flags,
                    reasoning=result.reasoning,
                    recommended_action=result.recommended_action,
                    scores_breakdown=result.scores_breakdown,
                )
                db.add(ai_analysis)

                if result.severity > 0:
                    action_taken = await execute_moderation(
                        db=db,
                        guild=message.guild,
                        member=member,
                        severity=result.severity,
                        reason=truncate(result.reasoning, 512),
                        risk_score=result.risk_score,
                        ai_reasoning=result.reasoning,
                        message=message,
                    )
                    ai_analysis.action_taken = action_taken
                    logger.info(
                        "[AI-MOD] guild=%s user=%s risk=%.1f sev=%d action=%s flags=%s",
                        message.guild.id, message.author.id, result.risk_score,
                        result.severity, action_taken, result.flags[:3],
                    )
                else:
                    await passive_trust_gain(db, message.author.id, message.guild.id)

                await apply_ai_trust_impact(
                    db, message.author.id, message.guild.id,
                    result.trust_impact, result.flags
                )

                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_message handler: %s", e, exc_info=True)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        async with AsyncSessionLocal() as db:
            try:
                await record_message_delete(db, message.id, message.guild.id)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_message_delete: %s", e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or after.author.bot:
            return
        if before.content == after.content:
            return

        async with AsyncSessionLocal() as db:
            try:
                await record_message_edit(db, after.id, after.guild.id, after.content)

                member = after.guild.get_member(after.author.id) or after.author
                if is_protected(member):
                    await db.commit()
                    return

                user_result = await db.execute(
                    select(User).where(User.id == after.author.id, User.guild_id == after.guild.id)
                )
                user_db = user_result.scalar_one_or_none()
                trust_score = user_db.trust_score if user_db else 100.0

                result = analyze_message(
                    content=after.content,
                    user_id=after.author.id,
                    guild_id=after.guild.id,
                    trust_score=trust_score,
                )

                if result.severity >= 2:
                    await execute_moderation(
                        db=db,
                        guild=after.guild,
                        member=member,
                        severity=result.severity,
                        reason=f"[Bearbeitete Nachricht] {truncate(result.reasoning, 400)}",
                        risk_score=result.risk_score,
                        ai_reasoning=result.reasoning,
                        message=after,
                    )

                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_message_edit: %s", e)

    async def _ensure_guild(self, db: AsyncSession, guild: discord.Guild):
        result = await db.execute(select(Guild).where(Guild.id == guild.id))
        g = result.scalar_one_or_none()
        if not g:
            g = Guild(
                id=guild.id,
                name=guild.name,
                icon_url=str(guild.icon.url) if guild.icon else None,
                owner_id=guild.owner_id,
                member_count=guild.member_count,
            )
            db.add(g)
            await db.flush()

    async def _ensure_channel(self, db: AsyncSession, channel: discord.TextChannel, guild: discord.Guild):
        result = await db.execute(select(Channel).where(Channel.id == channel.id))
        c = result.scalar_one_or_none()
        if not c:
            c = Channel(
                id=channel.id,
                guild_id=guild.id,
                name=channel.name,
                channel_type=str(channel.type),
                category_id=channel.category_id,
                category_name=channel.category.name if channel.category else None,
                is_nsfw=getattr(channel, "nsfw", False),
                position=getattr(channel, "position", 0),
            )
            db.add(c)
            await db.flush()


async def setup(bot: commands.Bot):
    await bot.add_cog(MessageEvents(bot))
