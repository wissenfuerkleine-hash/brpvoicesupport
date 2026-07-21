"""
Server-level event handlers: channels, roles, guild updates, webhooks, invites, etc.
"""

import discord
from discord.ext import commands
from database.connection import AsyncSessionLocal
from database.models import AuditLog, Channel, Guild
from sqlalchemy import select, update
from utils.logger import logger


class ServerEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        async with AsyncSessionLocal() as db:
            try:
                new_ch = Channel(
                    id=channel.id,
                    guild_id=channel.guild.id,
                    name=channel.name,
                    channel_type=str(channel.type),
                    category_id=channel.category_id,
                    category_name=channel.category.name if channel.category else None,
                    position=channel.position,
                )
                db.add(new_ch)
                log = AuditLog(
                    guild_id=channel.guild.id,
                    action="channel_create",
                    channel_id=channel.id,
                    channel_name=channel.name,
                    extra_data={"type": str(channel.type)},
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_guild_channel_create: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=channel.guild.id,
                    action="channel_delete",
                    channel_id=channel.id,
                    channel_name=channel.name,
                    extra_data={"type": str(channel.type)},
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_guild_channel_delete: %s", e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        async with AsyncSessionLocal() as db:
            try:
                changes = {}
                if before.name != after.name:
                    changes["name_before"] = before.name
                    changes["name_after"] = after.name
                if getattr(before, "topic", None) != getattr(after, "topic", None):
                    changes["topic_changed"] = True

                if changes:
                    await db.execute(
                        update(Channel)
                        .where(Channel.id == after.id)
                        .values(name=after.name)
                    )
                    log = AuditLog(
                        guild_id=after.guild.id,
                        action="channel_update",
                        channel_id=after.id,
                        channel_name=after.name,
                        extra_data=changes,
                    )
                    db.add(log)
                    await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_guild_channel_update: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=role.guild.id,
                    action="role_create",
                    extra_data={"role_id": role.id, "role_name": role.name},
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_guild_role_create: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=role.guild.id,
                    action="role_delete",
                    extra_data={"role_id": role.id, "role_name": role.name},
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_guild_role_delete: %s", e)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = {}
        if before.name != after.name:
            changes["name"] = {"before": before.name, "after": after.name}
        if before.permissions != after.permissions:
            changes["permissions_changed"] = True
        if before.color != after.color:
            changes["color_changed"] = True

        if changes:
            async with AsyncSessionLocal() as db:
                try:
                    log = AuditLog(
                        guild_id=after.guild.id,
                        action="role_update",
                        extra_data={"role_id": after.id, "role_name": after.name, "changes": changes},
                    )
                    db.add(log)
                    await db.commit()
                except Exception as e:
                    await db.rollback()
                    logger.error("Error in on_guild_role_update: %s", e)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changes = {}
        if before.name != after.name:
            changes["name"] = {"before": before.name, "after": after.name}
        if before.icon != after.icon:
            changes["icon_changed"] = True
        if before.owner_id != after.owner_id:
            changes["owner_changed"] = {"before": before.owner_id, "after": after.owner_id}

        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    update(Guild)
                    .where(Guild.id == after.id)
                    .values(name=after.name, member_count=after.member_count)
                )
                if changes:
                    log = AuditLog(
                        guild_id=after.id,
                        action="guild_update",
                        extra_data=changes,
                    )
                    db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_guild_update: %s", e)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.TextChannel):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=channel.guild.id,
                    action="webhooks_update",
                    channel_id=channel.id,
                    channel_name=channel.name,
                    extra_data={"warning": "Webhook changes detected"},
                )
                db.add(log)
                await db.commit()
                logger.warning("[SECURITY] Webhook updated in %s / %s", channel.guild.name, channel.name)
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_webhooks_update: %s", e)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=invite.guild.id,
                    action="invite_create",
                    user_id=invite.inviter.id if invite.inviter else None,
                    username=str(invite.inviter) if invite.inviter else None,
                    extra_data={
                        "code": invite.code,
                        "max_uses": invite.max_uses,
                        "temporary": invite.temporary,
                    },
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_invite_create: %s", e)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=invite.guild.id,
                    action="invite_delete",
                    extra_data={"code": invite.code},
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_invite_delete: %s", e)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=thread.guild.id,
                    action="thread_create",
                    channel_id=thread.id,
                    channel_name=thread.name,
                    extra_data={"parent_id": thread.parent_id},
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_thread_create: %s", e)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        async with AsyncSessionLocal() as db:
            try:
                log = AuditLog(
                    guild_id=thread.guild.id,
                    action="thread_delete",
                    channel_id=thread.id,
                    channel_name=thread.name,
                )
                db.add(log)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("Error in on_thread_delete: %s", e)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerEvents(bot))
