"""
utils/embeds.py
╰──➤ Discord embed helpers for ClaudePleX
"""

import discord
from datetime import datetime, timezone


def make_embed(
    title: str = "",
    description: str = "",
    color: int = 0x5865F2,
    footer: str = "",
    thumbnail: str = "",
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    return embed


def make_error_embed(message: str) -> discord.Embed:
    return make_embed(
        title="❌ Error",
        description=f"```\n{message[:1800]}\n```",
        color=0xED4245,
        footer="ClaudePleX · NCOM Systems"
    )
