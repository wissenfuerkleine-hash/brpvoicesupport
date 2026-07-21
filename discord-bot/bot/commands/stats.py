"""
Statistics slash commands: /serverstats /userstats /risk /dashboard
"""

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select, desc, func
from database.connection import AsyncSessionLocal
from database.models import User, AIAnalysis, AuditLog, ServerStats, VoiceSession
from services.stats_service import get_server_stats_summary
from services.trust_service import get_trust_score
from utils.helpers import has_admin_role, format_duration
from utils.logger import logger


class StatsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="serverstats", description="Serverstatistiken anzeigen")
    async def serverstats(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as db:
            stats = await get_server_stats_summary(db, interaction.guild.id)

        embed = discord.Embed(
            title=f"📊 Serverstatistiken — {interaction.guild.name}",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.add_field(name="Mitglieder", value=str(interaction.guild.member_count), inline=True)
        embed.add_field(name="Aktiv (24h)", value=str(stats["active_users_24h"]), inline=True)
        embed.add_field(name="Nachrichten (24h)", value=str(stats["messages_24h"]), inline=True)
        embed.add_field(name="Nachrichten (7 Tage)", value=str(stats["messages_7d"]), inline=True)
        embed.add_field(name="Verwarnungen gesamt", value=str(stats["warnings_total"]), inline=True)
        embed.add_field(name="Timeouts gesamt", value=str(stats["timeouts_total"]), inline=True)
        embed.add_field(name="Bans gesamt", value=str(stats["bans_total"]), inline=True)
        embed.add_field(name="KI-Flags gesamt", value=str(stats["ai_flags_total"]), inline=True)

        if stats["top_users"]:
            top_u = "\n".join(f"{i+1}. {u['username']} — {u['messages']}" for i, u in enumerate(stats["top_users"][:5]))
            embed.add_field(name="🏆 Top Benutzer", value=top_u, inline=True)

        if stats["top_channels"]:
            top_c = "\n".join(f"{i+1}. #{c['name']} — {c['messages']}" for i, c in enumerate(stats["top_channels"][:5]))
            embed.add_field(name="💬 Top Kanäle", value=top_c, inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="userstats", description="Benutzerstatistiken anzeigen")
    @app_commands.describe(member="Der Benutzer (optional)")
    async def userstats(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user

        if target != interaction.user and not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        async with AsyncSessionLocal() as db:
            user_r = await db.execute(
                select(User).where(User.id == target.id, User.guild_id == interaction.guild.id)
            )
            user_db = user_r.scalar_one_or_none()

            trust = await get_trust_score(db, target.id, interaction.guild.id)

            voice_r = await db.execute(
                select(func.sum(VoiceSession.duration_seconds))
                .where(VoiceSession.user_id == target.id, VoiceSession.guild_id == interaction.guild.id)
            )
            total_voice = voice_r.scalar() or 0

            ai_r = await db.execute(
                select(func.count(AIAnalysis.id))
                .where(AIAnalysis.user_id == target.id, AIAnalysis.guild_id == interaction.guild.id, AIAnalysis.severity > 0)
            )
            ai_flags = ai_r.scalar() or 0

        embed = discord.Embed(
            title=f"👤 Benutzerstatistiken — {target.display_name}",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if user_db:
            embed.add_field(name="Nachrichten", value=str(user_db.message_count), inline=True)
            embed.add_field(name="Voice-Zeit", value=format_duration(int(total_voice)), inline=True)
            embed.add_field(name="Trust-Score", value=f"{trust:.1f}/100", inline=True)
            embed.add_field(name="Risiko-Score", value=f"{user_db.risk_score:.1f}/100", inline=True)
            embed.add_field(name="Verwarnungen", value=str(user_db.warning_count), inline=True)
            embed.add_field(name="Timeouts", value=str(user_db.timeout_count), inline=True)
            embed.add_field(name="KI-Flags", value=str(ai_flags), inline=True)
            embed.add_field(name="Beigetreten", value=user_db.join_date.strftime("%d.%m.%Y") if user_db.join_date else "N/A", inline=True)
            embed.add_field(name="Zuletzt aktiv", value=user_db.last_seen.strftime("%d.%m.%Y %H:%M") if user_db.last_seen else "N/A", inline=True)
        else:
            embed.description = "Kein Datenbankprofil für diesen Benutzer."

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="risk", description="Risiko-Score eines Benutzers anzeigen")
    @app_commands.describe(member="Der Benutzer")
    async def risk_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            user_r = await db.execute(
                select(User).where(User.id == member.id, User.guild_id == interaction.guild.id)
            )
            user_db = user_r.scalar_one_or_none()

            recent_ai = await db.execute(
                select(AIAnalysis)
                .where(AIAnalysis.user_id == member.id, AIAnalysis.guild_id == interaction.guild.id)
                .order_by(desc(AIAnalysis.created_at))
                .limit(5)
            )
            analyses = recent_ai.scalars().all()

        risk = user_db.risk_score if user_db else 0.0
        level = "🟢 Niedrig" if risk < 20 else ("🟡 Mittel" if risk < 50 else ("🔴 Hoch" if risk < 80 else "⚫ Kritisch"))

        embed = discord.Embed(
            title=f"⚠️ Risiko-Analyse — {member.display_name}",
            color=discord.Color.red() if risk >= 50 else discord.Color.yellow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Risiko-Score", value=f"**{risk:.1f}/100** — {level}", inline=False)

        if analyses:
            lines = [
                f"`{a.created_at.strftime('%d.%m %H:%M')}` Score: {a.risk_score:.0f} | Flags: {', '.join(a.flags[:3]) if a.flags else 'keine'}"
                for a in analyses
            ]
            embed.add_field(name="Letzte KI-Analysen", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)



async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCommands(bot))
