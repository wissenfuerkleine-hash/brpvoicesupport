"""
Voice state event handler
"""

import discord
from discord.ext import commands
from database.connection import AsyncSessionLocal
from database.models import AuditLog
from services.stats_service import start_voice_session, end_voice_session
from utils.logger import logger


class VoiceEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return
        async with AsyncSessionLocal() as db:
            try:
                if before.channel is None and after.channel is not None:
                    await start_voice_session(
                        db,
                        member.guild.id,
                        member.id,
                        after.channel.id,
                        after.channel.name,
                    )
                    log = AuditLog(
                        guild_id=member.guild.id,
                        user_id=member.id,
                        username=str(member),
                        action="voice_join",
                        channel_id=after.channel.id,
                        channel_name=after.channel.name,
                        extra_data={"channel": after.channel.name},
                    )
                    db.add(log)

                elif before.channel is not None and after.channel is None:
                    await end_voice_session(db, member.guild.id, member.id)
                    log = AuditLog(
                        guild_id=member.guild.id,
                        user_id=member.id,
                        username=str(member),
                        action="voice_leave",
                        channel_id=before.channel.id,
                        channel_name=before.channel.name,
                        extra_data={"channel": before.channel.name},
                    )
                    db.add(log)

                elif before.channel != after.channel:
                    await end_voice_session(db, member.guild.id, member.id)
                    await start_voice_session(
                        db, member.guild.id, member.id,
                        after.channel.id, after.channel.name,
                    )
                    log = AuditLog(
                        guild_id=member.guild.id,
                        user_id=member.id,
                        username=str(member),
                        action="voice_move",
                        extra_data={"from": before.channel.name, "to": after.channel.name},
                    )
                    db.add(log)

                changes = {}
                if before.self_mute != after.self_mute:
                    changes["muted"] = after.self_mute
                if before.self_deaf != after.self_deaf:
                    changes["deafened"] = after.self_deaf
                if before.self_stream != after.self_stream:
                    changes["streaming"] = after.self_stream

                if changes and after.channel:
                    log = AuditLog(
                        guild_id=member.guild.id,
                        user_id=member.id,
                        username=str(member),
                        action="voice_state_change",
                        channel_id=after.channel.id,
                        channel_name=after.channel.name,
                        extra_data=changes,
                    )
                    db.add(log)

                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_voice_state_update: %s", e, exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceEvents(bot))
