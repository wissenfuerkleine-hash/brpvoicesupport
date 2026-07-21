"""
Moderation slash commands: /warn /unwarn /timeout /ban /unban /history /scan
"""

import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
from sqlalchemy import select, desc
from database.connection import AsyncSessionLocal
from database.models import User, Warning, Timeout, Ban, AuditLog
from services.moderation_service import (
    issue_manual_warning, remove_warning,
    issue_manual_timeout, issue_manual_ban, issue_unban,
)
from services.trust_service import get_trust_score
from ai.moderation_engine import analyze_message
from utils.helpers import has_admin_role, is_protected, format_duration, severity_color, severity_label
from config.settings import settings
from utils.logger import logger


def require_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not has_admin_role(interaction.user):
            await interaction.response.send_message(
                "❌ Keine Berechtigung. Nur Admins dürfen diesen Befehl nutzen.",
                ephemeral=True,
            )
            return False
        return True
    return app_commands.check(predicate)


class ModerationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Verwarnt einen Benutzer")
    @app_commands.describe(member="Der Benutzer", reason="Grund der Verwarnung")
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        if is_protected(member):
            return await interaction.response.send_message("❌ Dieser Benutzer ist geschützt.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            warning = await issue_manual_warning(db, interaction.guild, member, interaction.user, reason)
            await db.commit()

        embed = discord.Embed(
            title="⚠️ Verwarnung ausgestellt",
            color=discord.Color.yellow(),
        )
        embed.add_field(name="Benutzer", value=f"{member.mention} ({member.id})", inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Grund", value=reason, inline=False)
        embed.set_footer(text=f"Verwarnungs-ID: {warning.id}")
        await interaction.response.send_message(embed=embed)

        try:
            await member.send(f"⚠️ Du wurdest auf **{interaction.guild.name}** verwarnt.\nGrund: {reason}")
        except discord.Forbidden:
            pass

    @app_commands.command(name="unwarn", description="Entfernt eine Verwarnung")
    @app_commands.describe(warning_id="ID der Verwarnung")
    async def unwarn(self, interaction: discord.Interaction, warning_id: int):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            success = await remove_warning(db, warning_id, interaction.guild.id, interaction.user.id)
            await db.commit()

        if success:
            await interaction.response.send_message(f"✅ Verwarnung #{warning_id} entfernt.")
        else:
            await interaction.response.send_message(f"❌ Verwarnung #{warning_id} nicht gefunden.", ephemeral=True)

    @app_commands.command(name="timeout", description="Setzt einen Benutzer auf Timeout")
    @app_commands.describe(member="Der Benutzer", minutes="Dauer in Minuten", reason="Grund")
    async def timeout_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: int,
        reason: str,
    ):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        if is_protected(member):
            return await interaction.response.send_message("❌ Dieser Benutzer ist geschützt.", ephemeral=True)
        if minutes < 1 or minutes > 40320:
            return await interaction.response.send_message("❌ Dauer: 1–40320 Minuten.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            record = await issue_manual_timeout(db, interaction.guild, member, interaction.user, minutes * 60, reason)
            await db.commit()

        embed = discord.Embed(title="🔇 Timeout", color=discord.Color.orange())
        embed.add_field(name="Benutzer", value=f"{member.mention} ({member.id})", inline=True)
        embed.add_field(name="Dauer", value=format_duration(minutes * 60), inline=True)
        embed.add_field(name="Grund", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="Bannt einen Benutzer vom Server")
    @app_commands.describe(member="Der Benutzer", reason="Grund")
    async def ban_cmd(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str,
    ):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        if is_protected(member):
            return await interaction.response.send_message("❌ Dieser Benutzer ist geschützt.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            ban = await issue_manual_ban(db, interaction.guild, member, interaction.user, reason)
            await db.commit()

        embed = discord.Embed(title="🔨 Ban", color=discord.Color.red())
        embed.add_field(name="Benutzer", value=f"{member.mention} ({member.id})", inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Grund", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="Entbannt einen Benutzer")
    @app_commands.describe(user_id="Discord User-ID", reason="Grund")
    async def unban_cmd(self, interaction: discord.Interaction, user_id: str, reason: str):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.response.send_message("❌ Ungültige User-ID.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            success = await issue_unban(db, interaction.guild, uid, interaction.user, reason)
            await db.commit()

        if success:
            await interaction.response.send_message(f"✅ Benutzer {uid} wurde entbannt.")
        else:
            await interaction.response.send_message(f"❌ Benutzer {uid} ist nicht gebannt oder nicht gefunden.", ephemeral=True)

    @app_commands.command(name="history", description="Zeigt die Moderationshistorie eines Benutzers")
    @app_commands.describe(member="Der Benutzer")
    async def history(self, interaction: discord.Interaction, member: discord.Member):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            warn_r = await db.execute(
                select(Warning)
                .where(Warning.user_id == member.id, Warning.guild_id == interaction.guild.id)
                .order_by(desc(Warning.created_at))
                .limit(5)
            )
            warnings = warn_r.scalars().all()

            timeout_r = await db.execute(
                select(Timeout)
                .where(Timeout.user_id == member.id, Timeout.guild_id == interaction.guild.id)
                .order_by(desc(Timeout.created_at))
                .limit(5)
            )
            timeouts = timeout_r.scalars().all()

            ban_r = await db.execute(
                select(Ban)
                .where(Ban.user_id == member.id, Ban.guild_id == interaction.guild.id)
                .order_by(desc(Ban.created_at))
                .limit(3)
            )
            bans = ban_r.scalars().all()

            trust = await get_trust_score(db, member.id, interaction.guild.id)
            user_r = await db.execute(
                select(User).where(User.id == member.id, User.guild_id == interaction.guild.id)
            )
            user_db = user_r.scalar_one_or_none()

        embed = discord.Embed(
            title=f"📋 Moderationshistorie — {member.display_name}",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Trust-Score", value=f"{trust:.1f}/100", inline=True)
        embed.add_field(name="Risiko-Score", value=f"{user_db.risk_score:.1f}/100" if user_db else "N/A", inline=True)
        embed.add_field(name="Nachrichten", value=str(user_db.message_count if user_db else 0), inline=True)

        if warnings:
            warn_text = "\n".join(
                f"`#{w.id}` {w.created_at.strftime('%d.%m.%Y')} — {w.reason[:60]}"
                for w in warnings
            )
            embed.add_field(name=f"⚠️ Verwarnungen ({len(warnings)})", value=warn_text, inline=False)

        if timeouts:
            to_text = "\n".join(
                f"{t.created_at.strftime('%d.%m.%Y')} — {format_duration(t.duration_seconds)} — {t.reason[:50]}"
                for t in timeouts
            )
            embed.add_field(name=f"🔇 Timeouts ({len(timeouts)})", value=to_text, inline=False)

        if bans:
            ban_text = "\n".join(
                f"{b.created_at.strftime('%d.%m.%Y')} — {b.reason[:60]}"
                for b in bans
            )
            embed.add_field(name=f"🔨 Bans ({len(bans)})", value=ban_text, inline=False)

        if not warnings and not timeouts and not bans:
            embed.add_field(name="Verlauf", value="✅ Keine Einträge", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="scan", description="KI-Analyse einer Nachricht durchführen")
    @app_commands.describe(text="Der zu analysierende Text")
    async def scan(self, interaction: discord.Interaction, text: str):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        result = analyze_message(
            content=text,
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
        )

        embed = discord.Embed(
            title="🔍 KI-Analyse",
            color=severity_color(result.severity),
        )
        embed.add_field(name="Risiko-Score", value=f"{result.risk_score:.1f}/100", inline=True)
        embed.add_field(name="Schweregrad", value=f"{result.severity} — {severity_label(result.severity)}", inline=True)
        embed.add_field(name="Empfohlene Aktion", value=result.recommended_action, inline=True)
        embed.add_field(name="Erkannte Flags", value=(", ".join(result.flags) or "Keine") , inline=False)
        embed.add_field(name="Begründung", value=result.reasoning[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="trust", description="Trust-Score eines Benutzers anzeigen")
    @app_commands.describe(member="Der Benutzer")
    async def trust_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user

        if target != interaction.user and not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            trust = await get_trust_score(db, target.id, interaction.guild.id)
            user_r = await db.execute(
                select(User).where(User.id == target.id, User.guild_id == interaction.guild.id)
            )
            user_db = user_r.scalar_one_or_none()

        level = "🟢 Vertrauenswürdig" if trust >= 80 else ("🟡 Auffällig" if trust >= 50 else "🔴 Gefährlich")
        embed = discord.Embed(title=f"🛡️ Trust-Score — {target.display_name}", color=discord.Color.green() if trust >= 80 else (discord.Color.yellow() if trust >= 50 else discord.Color.red()))
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Trust-Score", value=f"**{trust:.1f}/100** — {level}", inline=False)
        embed.add_field(name="Risiko-Score", value=f"{user_db.risk_score:.1f}/100" if user_db else "N/A", inline=True)
        embed.add_field(name="Verwarnungen", value=str(user_db.warning_count if user_db else 0), inline=True)
        embed.add_field(name="Timeouts", value=str(user_db.timeout_count if user_db else 0), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="logs", description="Letzte Audit-Log-Einträge anzeigen")
    @app_commands.describe(limit="Anzahl der Einträge (max 20)")
    async def logs_cmd(self, interaction: discord.Interaction, limit: int = 10):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        limit = min(limit, 20)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AuditLog)
                .where(AuditLog.guild_id == interaction.guild.id)
                .order_by(desc(AuditLog.created_at))
                .limit(limit)
            )
            logs = result.scalars().all()

        if not logs:
            return await interaction.response.send_message("Keine Log-Einträge gefunden.", ephemeral=True)

        lines = []
        for log in logs:
            ts = log.created_at.strftime("%d.%m %H:%M")
            user = f"{log.username}" if log.username else "System"
            lines.append(f"`{ts}` **{log.action}** — {user}")

        embed = discord.Embed(
            title=f"📜 Audit-Log (letzte {len(logs)} Einträge)",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCommands(bot))
