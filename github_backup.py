"""
cogs/admin.py
╰──➤ Admin + Help commands for ClaudePleX
"""

import discord
from discord import app_commands
from discord.ext import commands
import logging
import platform
import psutil
import os
from datetime import datetime, timezone
from utils.embeds import make_embed

log = logging.getLogger("ClaudePleX.Admin")


class Admin(commands.Cog):
    """Admin utilities, /help, and bot info."""

    def __init__(self, bot: commands.Bot):
        self.bot       = bot
        self.start_time = datetime.now(timezone.utc)

    # ── /help ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="help", description="ClaudePleX command reference")
    async def help_cmd(self, interaction: discord.Interaction):
        embed = make_embed(
            title="⚡ ClaudePleX — Command Reference",
            description=(
                "**NCOM Systems PleX Bot + Claude AI + Sentient Backup**\n\n"

                "**🤖 Claude AI Chat**\n"
                "`/chat` — Chat with Claude (PleX-aware, remembers context)\n"
                "`/ask_plex` — Ask Claude a PleX-specific question\n"
                "`/chat_clear` — Reset conversation history in this channel\n\n"

                "**🔨 PleX Code Tooling**\n"
                "`/plex_build` — Generate PleX code from plain English\n"
                "`/plex_validate` — Validate PleX syntax + get diagnostics\n"
                "`/plex_explain` — Get a plain-English explanation of PleX code\n"
                "`/plex_new` — Create a new PleX file (.plx/.nude/.bun/etc.)\n"
                "`/plex_upload` — Upload a PleX file for analysis\n\n"

                "**🛡️ Sentient Backup System**\n"
                "```\nHail | @Drive |~| @Google Drive\n```"
                "`/backup_add` — Add a GitHub repo to the watchlist\n"
                "`/backup_now` — Immediately backup a repo (or all)\n"
                "`/backup_list` — List all watched repos + Drive links\n"
                "`/backup_remove` — Remove a repo from watchlist\n"
                "`/backup_status` — Check backup system health\n\n"

                "**⚙️ Admin**\n"
                "`/info` — Bot stats and system info\n"
                "`/help` — This menu\n"
            ),
            color=0x5865F2,
            footer="ClaudePleX v1.0 · NCOM Systems · github.com/pfn000/PleX"
        )
        await interaction.response.send_message(embed=embed)

    # ── /info ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="info", description="ClaudePleX bot information and stats")
    async def info(self, interaction: discord.Interaction):
        uptime   = datetime.now(timezone.utc) - self.start_time
        hours, r = divmod(int(uptime.total_seconds()), 3600)
        mins, _  = divmod(r, 60)

        embed = make_embed(
            title="⚡ ClaudePleX — Bot Info",
            description=(
                f"**Bot:** ClaudePleX v1.0\n"
                f"**Author:** NCOM Systems / Emmi (@Saidie000)\n"
                f"**App ID:** `1485711945888960512`\n\n"

                f"**🤖 AI Engine:** Claude (claude-sonnet-4)\n"
                f"**📝 Language:** NCOM Systems PleX\n"
                f"**🛡️ Backup:** GitHub → Google Drive\n\n"

                f"**⏱️ Uptime:** `{hours}h {mins}m`\n"
                f"**🏠 Servers:** `{len(self.bot.guilds)}`\n"
                f"**🐍 Python:** `{platform.python_version()}`\n"
                f"**📦 discord.py:** `{discord.__version__}`\n\n"

                f"```PleX\nHail | ClaudePleX\n"
                f"╰──➤ Status | Online\n"
                f"╰──➤ Uptime | {hours}h {mins}m\n"
                f"Sign~!!\n```"
            ),
            color=0x5865F2,
            footer="NCOM Systems © 2026 · All Rights Reserved"
        )
        await interaction.response.send_message(embed=embed)

    # ── Prefix command: !sync (owner only) ───────────────────────────────────
    @commands.command(name="sync")
    @commands.is_owner()
    async def sync(self, ctx: commands.Context):
        """Manually sync slash commands (owner only)."""
        synced = await self.bot.tree.sync()
        await ctx.send(f"✅ Synced `{len(synced)}` command(s)")

    @commands.command(name="reload")
    @commands.is_owner()
    async def reload_cog(self, ctx: commands.Context, cog: str):
        """Reload a cog by name (owner only). Example: !reload cogs.claude_chat"""
        try:
            await self.bot.reload_extension(cog)
            await ctx.send(f"✅ Reloaded `{cog}`")
        except Exception as e:
            await ctx.send(f"❌ Failed: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
