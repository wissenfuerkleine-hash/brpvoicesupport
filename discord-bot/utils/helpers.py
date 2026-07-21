"""
Utility helpers for the Discord bot.
"""

import re
import discord
from datetime import datetime, timezone, timedelta
from config.settings import settings


def has_admin_role(member: discord.Member) -> bool:
    return any(r.id == settings.admin_role_id for r in member.roles)


def has_whitelist_role(member: discord.Member) -> bool:
    return any(r.id == settings.whitelist_role_id for r in member.roles)


def is_protected(member: discord.Member) -> bool:
    return has_admin_role(member) or has_whitelist_role(member) or member.bot


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}m" if m else f"{h}h"
    else:
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        return f"{d}d {h}h" if h else f"{d}d"


def make_embed(
    title: str,
    description: str = "",
    color: discord.Color = discord.Color.blue(),
    fields: list = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    if fields:
        for f in fields:
            embed.add_field(name=f.get("name", ""), value=f.get("value", ""), inline=f.get("inline", True))
    return embed


def severity_color(severity: int) -> discord.Color:
    colors = {
        0: discord.Color.green(),
        1: discord.Color.yellow(),
        2: discord.Color.orange(),
        3: discord.Color.red(),
        4: discord.Color.dark_red(),
    }
    return colors.get(severity, discord.Color.greyple())


def severity_label(severity: int) -> str:
    labels = {
        0: "Kein Verstoß",
        1: "Warnung",
        2: "Timeout (10 Min)",
        3: "Timeout (1 Std)",
        4: "Permanent Mute",
    }
    return labels.get(severity, "Unbekannt")


def truncate(text: str, max_len: int = 1024) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def clean_content(content: str) -> str:
    return re.sub(r"[^\w\s.,!?äöüÄÖÜß-]", "", content).strip()


def account_age_days(created_at: datetime) -> int:
    now = datetime.now(timezone.utc)
    delta = now - created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else now - created_at
    return max(0, delta.days)


def join_age_days(joined_at: datetime) -> int:
    if not joined_at:
        return 0
    now = datetime.now(timezone.utc)
    delta = now - joined_at.replace(tzinfo=timezone.utc) if joined_at.tzinfo is None else now - joined_at
    return max(0, delta.days)
