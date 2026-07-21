"""
Discord Bot Client — sets up intents, loads cogs, syncs slash commands.
"""

import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone
from database.connection import init_db, AsyncSessionLocal
from database.models import Guild
from sqlalchemy import select, update
from utils.logger import logger
from config.settings import settings


COGS = [
    "bot.events.message_events",
    "bot.events.member_events",
    "bot.events.voice_events",
    "bot.events.server_events",
    "bot.commands.moderation",
    "bot.commands.stats",
    "bot.commands.settings",
    "bot.commands.dashboard",
]


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        logger.info("Initializing database...")
        await init_db()

        logger.info("Loading cogs...")
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as e:
                logger.error("Failed to load cog %s: %s", cog, e, exc_info=True)

        logger.info("Syncing slash commands...")
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash commands.", len(synced))
        except Exception as e:
            logger.error("Failed to sync commands: %s", e, exc_info=True)

        self.stats_task.start()

    async def on_ready(self):
        logger.info("Bot ready as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} Server | /help",
            )
        )

        async with AsyncSessionLocal() as db:
            for guild in self.guilds:
                result = await db.execute(select(Guild).where(Guild.id == guild.id))
                g = result.scalar_one_or_none()
                if not g:
                    g = Guild(
                        id=guild.id,
                        name=guild.name,
                        icon_url=str(guild.icon.url) if guild.icon else None,
                        owner_id=guild.owner_id,
                        member_count=guild.member_count,
                        is_active=True,
                    )
                    db.add(g)
                else:
                    g.name = guild.name
                    g.member_count = guild.member_count
                    g.is_active = True
            await db.commit()

    async def on_guild_join(self, guild: discord.Guild):
        logger.info("Joined guild: %s (%s)", guild.name, guild.id)
        async with AsyncSessionLocal() as db:
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
                await db.commit()

        try:
            await self.tree.sync(guild=guild)
        except Exception as e:
            logger.warning("Could not sync commands to guild %s: %s", guild.id, e)

    async def on_guild_remove(self, guild: discord.Guild):
        logger.info("Removed from guild: %s (%s)", guild.name, guild.id)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Guild).where(Guild.id == guild.id).values(is_active=False)
            )
            await db.commit()

    async def on_error(self, event_method: str, *args, **kwargs):
        logger.error("Unhandled error in %s", event_method, exc_info=True)

    @tasks.loop(hours=1)
    async def stats_task(self):
        """Periodic task: update guild member counts."""
        try:
            async with AsyncSessionLocal() as db:
                for guild in self.guilds:
                    await db.execute(
                        update(Guild)
                        .where(Guild.id == guild.id)
                        .values(member_count=guild.member_count)
                    )
                await db.commit()
            logger.debug("Stats task completed: updated %d guilds", len(self.guilds))
        except Exception as e:
            logger.error("Stats task error: %s", e, exc_info=True)

    @stats_task.before_loop
    async def before_stats_task(self):
        await self.wait_until_ready()


def create_bot() -> DiscordBot:
    return DiscordBot()
