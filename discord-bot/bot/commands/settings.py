"""
Settings slash commands: /settings /reload /backup /announce
"""

import discord
from discord.ext import commands
from discord import app_commands
from sqlalchemy import select
from database.connection import AsyncSessionLocal
from database.models import DashboardSettings, Guild
from utils.helpers import has_admin_role
from utils.logger import logger


class SettingsCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="settings", description="Bot-Einstellungen für diesen Server anzeigen/ändern")
    async def settings_cmd(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DashboardSettings).where(DashboardSettings.guild_id == interaction.guild.id)
            )
            s = result.scalar_one_or_none()

        if not s:
            embed = discord.Embed(
                title="⚙️ Server-Einstellungen",
                description="Noch keine Einstellungen konfiguriert. Standard-Einstellungen werden verwendet.",
                color=discord.Color.blue(),
            )
        else:
            embed = discord.Embed(title="⚙️ Server-Einstellungen", color=discord.Color.blue())
            embed.add_field(name="Auto-Moderation", value="✅" if s.auto_moderation else "❌", inline=True)
            embed.add_field(name="Raid-Schutz", value="✅" if s.raid_protection else "❌", inline=True)
            embed.add_field(name="Spam-Schutz", value="✅" if s.spam_protection else "❌", inline=True)
            embed.add_field(name="Link-Filter", value="✅" if s.link_filter else "❌", inline=True)
            embed.add_field(name="Invite-Filter", value="✅" if s.invite_filter else "❌", inline=True)
            embed.add_field(name="CAPS-Filter", value="✅" if s.caps_filter else "❌", inline=True)
            embed.add_field(name="Max. Mentions", value=str(s.mention_limit), inline=True)
            embed.add_field(name="Warn-Schwelle", value=str(s.warn_threshold), inline=True)
            embed.add_field(name="Perma-Mute Schwelle", value=str(s.perma_mute_threshold), inline=True)

        embed.set_footer(text="Einstellungen werden über die REST-API oder Bubble verwaltet.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="reload", description="Bot-Cogs neu laden")
    async def reload_cmd(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        cogs = [
            "bot.events.message_events",
            "bot.events.member_events",
            "bot.events.voice_events",
            "bot.events.server_events",
            "bot.commands.moderation",
            "bot.commands.stats",
            "bot.commands.settings",
        ]
        reloaded = []
        failed = []
        for cog in cogs:
            try:
                await self.bot.reload_extension(cog)
                reloaded.append(cog.split(".")[-1])
            except Exception as e:
                failed.append(f"{cog}: {e}")
                logger.error("Reload failed for %s: %s", cog, e)

        embed = discord.Embed(title="🔄 Reload", color=discord.Color.green() if not failed else discord.Color.orange())
        if reloaded:
            embed.add_field(name="✅ Erfolgreich", value="\n".join(reloaded), inline=False)
        if failed:
            embed.add_field(name="❌ Fehlgeschlagen", value="\n".join(failed)[:1024], inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="announce", description="Ankündigung in einem Kanal senden")
    @app_commands.describe(channel="Ziel-Kanal", message="Nachricht", title="Titel (optional)")
    async def announce_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
        title: str = "📢 Ankündigung",
    ):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)

        embed = discord.Embed(
            title=title,
            description=message,
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Von {interaction.user.display_name}")
        try:
            await channel.send(embed=embed)
            await interaction.response.send_message(f"✅ Ankündigung in {channel.mention} gesendet.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Keine Berechtigung für diesen Kanal.", ephemeral=True)

    @app_commands.command(name="backup", description="Erstellt einen Daten-Backup-Hinweis")
    async def backup_cmd(self, interaction: discord.Interaction):
        if not has_admin_role(interaction.user):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        embed = discord.Embed(
            title="💾 Backup",
            description=(
                "Backups werden über die Datenbank verwaltet.\n\n"
                "Nutze `GET /api/backup` in der REST-API um einen vollständigen Datenbankexport zu erhalten.\n"
                "Railway bietet automatische PostgreSQL-Backups in der Pro-Version."
            ),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SettingsCommands(bot))
