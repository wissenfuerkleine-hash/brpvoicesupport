"""
Discord Dashboard — vollständige Server-Verwaltung über Slash Commands und Buttons.
Kein externes Dashboard nötig.
"""

import discord
from discord.ext import commands
from discord import app_commands, ui
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, desc, func
from database.connection import AsyncSessionLocal
from database.models import (
    User, Guild, Warning, Timeout, Ban,
    AuditLog, AIAnalysis, Channel, VoiceSession, DashboardSettings
)
from services.stats_service import get_server_stats_summary
from services.trust_service import get_trust_score
from utils.helpers import has_admin_role, format_duration, severity_color
from utils.logger import logger


# ---------------------------------------------------------------------------
# Helper: Build embeds
# ---------------------------------------------------------------------------

async def build_overview_embed(guild: discord.Guild) -> discord.Embed:
    async with AsyncSessionLocal() as db:
        stats = await get_server_stats_summary(db, guild.id)

        warn_count = (await db.execute(
            select(func.count(Warning.id)).where(Warning.guild_id == guild.id, Warning.is_active == True)
        )).scalar() or 0

        muted_count = (await db.execute(
            select(func.count(User.id)).where(User.guild_id == guild.id, User.is_perma_muted == True)
        )).scalar() or 0

        high_risk = (await db.execute(
            select(func.count(User.id)).where(User.guild_id == guild.id, User.risk_score >= 50)
        )).scalar() or 0

    embed = discord.Embed(
        title=f"🖥️ Dashboard — {guild.name}",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="👥 Mitglieder", value=f"**{guild.member_count}**", inline=True)
    embed.add_field(name="💬 Nachrichten (24h)", value=f"**{stats['messages_24h']}**", inline=True)
    embed.add_field(name="🟢 Aktive User (24h)", value=f"**{stats['active_users_24h']}**", inline=True)
    embed.add_field(name="⚠️ Aktive Verwarnungen", value=f"**{warn_count}**", inline=True)
    embed.add_field(name="🔴 Hoch-Risiko User", value=f"**{high_risk}**", inline=True)
    embed.add_field(name="🔇 Permanent Gemutet", value=f"**{muted_count}**", inline=True)
    embed.add_field(name="🤖 KI-Flags (gesamt)", value=f"**{stats['ai_flags_total']}**", inline=True)
    embed.add_field(name="🔨 Bans (gesamt)", value=f"**{stats['bans_total']}**", inline=True)
    embed.add_field(name="📊 Nachrichten (7 Tage)", value=f"**{stats['messages_7d']}**", inline=True)

    if stats["top_users"]:
        top = "\n".join(f"`{i+1}.` {u['username']} — {u['messages']} Nachrichten" for i, u in enumerate(stats["top_users"][:3]))
        embed.add_field(name="🏆 Top Benutzer", value=top, inline=True)

    if stats["top_channels"]:
        top = "\n".join(f"`{i+1}.` #{c['name']} — {c['messages']}" for i, c in enumerate(stats["top_channels"][:3]))
        embed.add_field(name="💬 Top Kanäle", value=top, inline=True)

    embed.set_footer(text="Nutze die Buttons unten für Details")
    return embed


async def build_moderation_embed(guild_id: int) -> discord.Embed:
    async with AsyncSessionLocal() as db:
        recent_warns = (await db.execute(
            select(Warning).where(Warning.guild_id == guild_id, Warning.is_active == True)
            .order_by(desc(Warning.created_at)).limit(5)
        )).scalars().all()

        recent_timeouts = (await db.execute(
            select(Timeout).where(Timeout.guild_id == guild_id, Timeout.is_active == True)
            .order_by(desc(Timeout.created_at)).limit(5)
        )).scalars().all()

        perma_muted = (await db.execute(
            select(User).where(User.guild_id == guild_id, User.is_perma_muted == True)
            .order_by(desc(User.last_seen)).limit(10)
        )).scalars().all()

    embed = discord.Embed(
        title="⚖️ Moderationsübersicht",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc),
    )

    if recent_warns:
        lines = [f"`#{w.id}` {w.created_at.strftime('%d.%m %H:%M')} — <@{w.user_id}> — {w.reason[:40]}" for w in recent_warns]
        embed.add_field(name="⚠️ Neueste Verwarnungen", value="\n".join(lines), inline=False)

    if recent_timeouts:
        lines = [f"{t.created_at.strftime('%d.%m %H:%M')} — <@{t.user_id}> — {format_duration(t.duration_seconds)}" for t in recent_timeouts]
        embed.add_field(name="🔇 Aktive Timeouts", value="\n".join(lines), inline=False)

    if perma_muted:
        lines = [f"<@{u.id}> `{u.username}` — Risk: {u.risk_score:.0f}" for u in perma_muted]
        embed.add_field(
            name="🚫 Permanent Gemutet (Admin-Aktion erforderlich)",
            value="\n".join(lines),
            inline=False,
        )
        embed.color = discord.Color.red()
    else:
        embed.add_field(name="🚫 Permanent Gemutet", value="✅ Keine Einträge", inline=False)

    return embed


async def build_risk_embed(guild_id: int) -> discord.Embed:
    async with AsyncSessionLocal() as db:
        high_risk_users = (await db.execute(
            select(User).where(User.guild_id == guild_id, User.risk_score >= 30)
            .order_by(desc(User.risk_score)).limit(10)
        )).scalars().all()

        low_trust_users = (await db.execute(
            select(User).where(User.guild_id == guild_id, User.trust_score < 50)
            .order_by(User.trust_score.asc()).limit(10)
        )).scalars().all()

    embed = discord.Embed(
        title="🎯 Risiko & Trust Analyse",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )

    if high_risk_users:
        lines = []
        for u in high_risk_users:
            level = "⚫" if u.risk_score >= 80 else ("🔴" if u.risk_score >= 60 else ("🟡" if u.risk_score >= 40 else "🟢"))
            lines.append(f"{level} `{u.username}` — Risk: **{u.risk_score:.0f}** | Trust: **{u.trust_score:.0f}**")
        embed.add_field(name="🔴 Hoch-Risiko Benutzer", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="🔴 Hoch-Risiko Benutzer", value="✅ Keine auffälligen Benutzer", inline=False)

    if low_trust_users:
        lines = [f"`{u.username}` — Trust: **{u.trust_score:.0f}** | Verwarnungen: {u.warning_count}" for u in low_trust_users]
        embed.add_field(name="📉 Niedriger Trust-Score", value="\n".join(lines), inline=False)

    return embed


async def build_logs_embed(guild_id: int) -> discord.Embed:
    async with AsyncSessionLocal() as db:
        logs = (await db.execute(
            select(AuditLog).where(AuditLog.guild_id == guild_id)
            .order_by(desc(AuditLog.created_at)).limit(15)
        )).scalars().all()

    embed = discord.Embed(
        title="📜 Letzte Aktionen (Audit-Log)",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc),
    )

    if logs:
        action_icons = {
            "member_join": "➕", "member_leave": "➖", "warn": "⚠️",
            "manual_warn": "⚠️", "timeout": "🔇", "long_timeout": "🔇",
            "perma_mute": "🚫", "manual_ban": "🔨", "member_update": "✏️",
            "voice_join": "🎙️", "voice_leave": "🔕", "channel_create": "📢",
            "channel_delete": "🗑️", "message_delete": "🗑️",
        }
        lines = []
        for log in logs:
            icon = action_icons.get(log.action, "📌")
            ts = log.created_at.strftime("%d.%m %H:%M")
            user = f"`{log.username}`" if log.username else "System"
            lines.append(f"{icon} `{ts}` {log.action} — {user}")
        embed.description = "\n".join(lines)
    else:
        embed.description = "Keine Einträge vorhanden."

    return embed


async def build_settings_embed(guild_id: int) -> discord.Embed:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DashboardSettings).where(DashboardSettings.guild_id == guild_id)
        )
        s = result.scalar_one_or_none()

    embed = discord.Embed(
        title="⚙️ Server-Einstellungen",
        color=discord.Color.greyple(),
        timestamp=datetime.now(timezone.utc),
    )

    if s:
        def yn(v): return "✅ Aktiv" if v else "❌ Inaktiv"
        embed.add_field(name="🤖 Auto-Moderation", value=yn(s.auto_moderation), inline=True)
        embed.add_field(name="🛡️ Raid-Schutz", value=yn(s.raid_protection), inline=True)
        embed.add_field(name="🚫 Spam-Schutz", value=yn(s.spam_protection), inline=True)
        embed.add_field(name="🔗 Link-Filter", value=yn(s.link_filter), inline=True)
        embed.add_field(name="📨 Invite-Filter", value=yn(s.invite_filter), inline=True)
        embed.add_field(name="🔤 CAPS-Filter", value=yn(s.caps_filter), inline=True)
        embed.add_field(name="📢 Max. Mentions", value=str(s.mention_limit), inline=True)
        embed.add_field(name="⚠️ Warn-Schwelle", value=str(s.warn_threshold), inline=True)
        embed.add_field(name="🚫 Perma-Mute Schwelle", value=str(s.perma_mute_threshold), inline=True)
    else:
        embed.description = "Noch keine Einstellungen gesetzt. Standard-Einstellungen sind aktiv.\nNutze `/settings-update` um Einstellungen zu konfigurieren."

    return embed


# ---------------------------------------------------------------------------
# Dashboard View with Buttons
# ---------------------------------------------------------------------------

class DashboardView(ui.View):
    def __init__(self, guild: discord.Guild, author_id: int):
        super().__init__(timeout=300)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Nur der Befehlsauslöser kann die Buttons nutzen.", ephemeral=True)
            return False
        return True

    @ui.button(label="📊 Übersicht", style=discord.ButtonStyle.primary, custom_id="dash_overview")
    async def overview(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        embed = await build_overview_embed(self.guild)
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="⚖️ Moderation", style=discord.ButtonStyle.danger, custom_id="dash_mod")
    async def moderation(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        embed = await build_moderation_embed(self.guild.id)
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="🎯 Risiko", style=discord.ButtonStyle.danger, custom_id="dash_risk")
    async def risk(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        embed = await build_risk_embed(self.guild.id)
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="📜 Logs", style=discord.ButtonStyle.secondary, custom_id="dash_logs")
    async def logs(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        embed = await build_logs_embed(self.guild.id)
        await interaction.edit_original_response(embed=embed, view=self)

    @ui.button(label="⚙️ Einstellungen", style=discord.ButtonStyle.secondary, custom_id="dash_settings")
    async def settings(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        embed = await build_settings_embed(self.guild.id)
        await interaction.edit_original_response(embed=embed, view=self)


# ---------------------------------------------------------------------------
# Unmute Modal
# ---------------------------------------------------------------------------

class UnmuteModal(ui.Modal, title="Benutzer entmuten"):
    user_id_input = ui.TextInput(
        label="Discord User-ID",
        placeholder="z.B. 1478376025585881119",
        min_length=10,
        max_length=25,
    )
    reason_input = ui.TextInput(
        label="Grund für Entmutung",
        placeholder="z.B. Fall geprüft, kein weiterer Verstoß",
        style=discord.TextStyle.short,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id_input.value.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Ungültige User-ID.", ephemeral=True)

        member = interaction.guild.get_member(uid)
        if not member:
            return await interaction.response.send_message(f"❌ Benutzer {uid} nicht auf dem Server gefunden.", ephemeral=True)

        try:
            await member.timeout(None, reason=f"[Admin-Entmutung] {self.reason_input.value}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Keine Berechtigung zum Entmuten.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(User.id == uid, User.guild_id == interaction.guild.id)
            )
            user_db = result.scalar_one_or_none()
            if user_db:
                user_db.is_perma_muted = False
            log = AuditLog(
                guild_id=interaction.guild.id,
                user_id=uid,
                username=str(member),
                moderator_id=interaction.user.id,
                moderator_name=str(interaction.user),
                action="admin_unmute",
                ai_reasoning=self.reason_input.value,
            )
            db.add(log)
            await db.commit()

        await interaction.response.send_message(
            f"✅ **{member.display_name}** wurde entmutet.\nGrund: {self.reason_input.value}",
            ephemeral=False,
        )


# ---------------------------------------------------------------------------
# Moderation View (Perma-Mute management)
# ---------------------------------------------------------------------------

class ModerationActionView(ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Nur der Befehlsauslöser kann die Buttons nutzen.", ephemeral=True)
            return False
        if not has_admin_role(interaction.user):
            await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
            return False
        return True

    @ui.button(label="🔓 Benutzer entmuten", style=discord.ButtonStyle.success)
    async def unmute_user(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(UnmuteModal())

    @ui.button(label="🔄 Aktualisieren", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        embed = await build_moderation_embed(interaction.guild.id)
        await interaction.edit_original_response(embed=embed, view=self)


# ---------------------------------------------------------------------------
# Settings update command
# ---------------------------------------------------------------------------

class SettingsModal(ui.Modal, title="Server-Einstellungen"):
    mention_limit = ui.TextInput(label="Max. Mentions pro Nachricht", default="5", min_length=1, max_length=3)
    warn_threshold = ui.TextInput(label="Warn-Schwelle (Anzahl bevor Timeout)", default="3", min_length=1, max_length=2)
    perma_mute_threshold = ui.TextInput(label="Perma-Mute Schwelle", default="8", min_length=1, max_length=2)
    min_account_age = ui.TextInput(label="Mindest-Account-Alter (Tage)", default="7", min_length=1, max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DashboardSettings).where(DashboardSettings.guild_id == interaction.guild.id)
            )
            s = result.scalar_one_or_none()
            if not s:
                s = DashboardSettings(guild_id=interaction.guild.id)
                db.add(s)

            try:
                s.mention_limit = int(self.mention_limit.value)
                s.warn_threshold = int(self.warn_threshold.value)
                s.perma_mute_threshold = int(self.perma_mute_threshold.value)
                s.min_account_age_days = int(self.min_account_age.value)
            except ValueError:
                return await interaction.response.send_message("❌ Bitte nur Zahlen eingeben.", ephemeral=True)

            await db.commit()

        await interaction.response.send_message("✅ Einstellungen gespeichert!", ephemeral=True)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class DashboardCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="dashboard", description="Vollständiges Server-Dashboard")
    async def dashboard(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        embed = await build_overview_embed(interaction.guild)
        view = DashboardView(interaction.guild, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="modpanel", description="Moderations-Panel mit Aktions-Buttons")
    async def modpanel(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        embed = await build_moderation_embed(interaction.guild.id)
        view = ModerationActionView(interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="unmute", description="Permanent gemuteten Benutzer entmuten")
    @app_commands.describe(member="Der zu entmutende Benutzer", reason="Grund")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        try:
            await member.timeout(None, reason=f"[Admin-Entmutung] {reason}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Keine Berechtigung zum Entmuten.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(User.id == member.id, User.guild_id == interaction.guild.id)
            )
            user_db = result.scalar_one_or_none()
            if user_db:
                user_db.is_perma_muted = False
            log = AuditLog(
                guild_id=interaction.guild.id,
                user_id=member.id,
                username=str(member),
                moderator_id=interaction.user.id,
                moderator_name=str(interaction.user),
                action="admin_unmute",
                ai_reasoning=reason,
            )
            db.add(log)
            await db.commit()

        embed = discord.Embed(
            title="✅ Benutzer entmutet",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Benutzer", value=f"{member.mention} ({member.id})", inline=True)
        embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
        embed.add_field(name="Grund", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

        try:
            await member.send(
                f"✅ Du wurdest auf **{interaction.guild.name}** entmutet.\n"
                f"Grund: {reason}\nBitte halte dich in Zukunft an die Regeln."
            )
        except discord.Forbidden:
            pass

    @app_commands.command(name="settings-update", description="Bot-Einstellungen per Formular anpassen")
    async def settings_update(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        await interaction.response.send_modal(SettingsModal())

    @app_commands.command(name="perma-list", description="Alle permanent gemuteten Benutzer anzeigen")
    async def perma_list(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(
                    User.guild_id == interaction.guild.id,
                    User.is_perma_muted == True,
                ).order_by(desc(User.last_seen))
            )
            users = result.scalars().all()

        if not users:
            return await interaction.response.send_message("✅ Keine permanent gemuteten Benutzer.", ephemeral=True)

        embed = discord.Embed(
            title="🚫 Permanent Gemutet — Admin-Aktion erforderlich",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        lines = []
        for u in users:
            member = interaction.guild.get_member(u.id)
            mention = member.mention if member else f"`{u.username}`"
            lines.append(
                f"{mention} | Risk: **{u.risk_score:.0f}** | "
                f"Warns: {u.warning_count} | Zuletzt: {u.last_seen.strftime('%d.%m.%Y') if u.last_seen else 'N/A'}"
            )
        embed.description = "\n".join(lines[:20])
        embed.set_footer(text=f"Gesamt: {len(users)} | /unmute @user zum Entmuten")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(DashboardCommands(bot))
