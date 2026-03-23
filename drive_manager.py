"""
cogs/plex_code.py
╰──➤ PleX code tooling — build, validate, explain, create NCOM Systems PleX files in Discord
"""

import discord
from discord import app_commands
from discord.ext import commands
import anthropic
import os
import asyncio
import logging
import io
from datetime import datetime
from utils.plex_validator import PlexValidator, FileType
from utils.plex_context import PLEX_SYSTEM_PROMPT
from utils.embeds import make_embed, make_error_embed

log = logging.getLogger("ClaudePleX.PleX")

CLAUDE_MODEL = "claude-sonnet-4-20250514"

# File type choices for slash command
PLEX_FILE_TYPES = [
    app_commands.Choice(name=".plx  — Brain (primary logic)",         value="plx"),
    app_commands.Choice(name=".plxcode — Brain (alt extension)",       value="plxcode"),
    app_commands.Choice(name=".attributes — Body (assets/links)",      value="attributes"),
    app_commands.Choice(name=".mf  — Manifesto (zero-copy index)",     value="mf"),
    app_commands.Choice(name=".bun — Bundle (compressed data)",        value="bun"),
    app_commands.Choice(name=".nude — Nude Language (NCOM JS/TS alt)", value="nude"),
]


class PlexCode(commands.Cog):
    """PleX code commands — validate, build, explain, create files."""

    def __init__(self, bot: commands.Bot):
        self.bot       = bot
        self.ai        = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.validator = PlexValidator()

    # ── /plex_validate ────────────────────────────────────────────────────────
    @app_commands.command(
        name="plex_validate",
        description="Validate PleX code syntax and get diagnostics"
    )
    @app_commands.describe(code="PleX code to validate (paste without code fences)")
    async def plex_validate(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer()

        result = self.validator.validate(code)
        color  = 0x57F287 if result["valid"] else 0xED4245

        lines = [f"```\n{code[:1000]}\n```"]
        if result["errors"]:
            lines.append("**❌ Errors:**")
            lines += [f"`{e}`" for e in result["errors"]]
        if result["warnings"]:
            lines.append("**⚠️ Warnings:**")
            lines += [f"`{w}`" for w in result["warnings"]]
        if result["autocorrects"]:
            lines.append("**🔧 Autocorrections applied:**")
            lines += [f"`{a}`" for a in result["autocorrects"]]
        if result["valid"]:
            lines.append("**✅ Syntax valid — ready to run**")

        embed = make_embed(
            title="🔍 PleX Validator",
            description="\n".join(lines)[:3900],
            color=color,
            footer="NCOM Systems PleX · ClaudePleX"
        )
        await interaction.followup.send(embed=embed)

    # ── /plex_explain ─────────────────────────────────────────────────────────
    @app_commands.command(
        name="plex_explain",
        description="Ask Claude to explain PleX code in plain English"
    )
    @app_commands.describe(code="PleX code to explain")
    async def plex_explain(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(thinking=True)

        prompt = (
            "Explain the following PleX code in plain English. "
            "Be concise — 3–5 sentences max. Reference NCOM Systems terminology.\n\n"
            f"```PleX\n{code}\n```"
        )

        try:
            response = await asyncio.to_thread(self._claude, prompt)
            embed = make_embed(
                title="📖 PleX Explanation",
                description=f"**Code:**\n```PleX\n{code[:600]}\n```\n\n**Explanation:**\n{response[:1200]}",
                color=0x5865F2,
                footer="NCOM Systems PleX · ClaudePleX"
            )
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(embed=make_error_embed(str(e)))

    # ── /plex_build ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="plex_build",
        description="Generate PleX code from a plain-English description"
    )
    @app_commands.describe(description="What should the PleX code do?")
    async def plex_build(self, interaction: discord.Interaction, description: str):
        await interaction.response.defer(thinking=True)

        prompt = (
            "Generate valid PleX code for the following task. "
            "Return ONLY the PleX code block, nothing else.\n\n"
            f"Task: {description}"
        )

        try:
            response = await asyncio.to_thread(self._claude, prompt)
            # Strip any accidental markdown fences
            code = response.replace("```PleX", "").replace("```plex", "").replace("```", "").strip()

            # Auto-validate
            result = self.validator.validate(code)
            status = "✅ Valid" if result["valid"] else "⚠️ Has warnings"

            embed = make_embed(
                title="🔨 PleX Build",
                description=(
                    f"**Task:** {description}\n\n"
                    f"**Generated PleX:**\n```PleX\n{code[:1800]}\n```\n"
                    f"**Status:** {status}"
                ),
                color=0x57F287 if result["valid"] else 0xFEE75C,
                footer="NCOM Systems PleX · ClaudePleX"
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(embed=make_error_embed(str(e)))

    # ── /plex_new ─────────────────────────────────────────────────────────────
    @app_commands.command(
        name="plex_new",
        description="Create a new PleX file and get it as a Discord attachment"
    )
    @app_commands.describe(
        filename="File name (without extension)",
        file_type="File type to create",
        content="Optional initial content (leave blank for template)"
    )
    @app_commands.choices(file_type=PLEX_FILE_TYPES)
    async def plex_new(
        self,
        interaction: discord.Interaction,
        filename: str,
        file_type: app_commands.Choice[str],
        content: str = ""
    ):
        await interaction.response.defer()

        ext       = file_type.value
        full_name = f"{filename}.{ext}"

        # Generate template if no content given
        if not content.strip():
            content = await asyncio.to_thread(
                self._generate_template, ext, filename
            )

        file_bytes = content.encode("utf-8")
        discord_file = discord.File(
            io.BytesIO(file_bytes),
            filename=full_name,
            description=f"NCOM Systems PleX file — {full_name}"
        )

        embed = make_embed(
            title=f"📄 New PleX File — `{full_name}`",
            description=(
                f"**Type:** `{file_type.name}`\n"
                f"**Size:** {len(file_bytes)} bytes\n\n"
                f"Preview:\n```PleX\n{content[:500]}\n```"
            ),
            color=0x5865F2,
            footer="NCOM Systems · Download and open in VS Code"
        )
        await interaction.followup.send(embed=embed, file=discord_file)

    # ── /plex_upload ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="plex_upload",
        description="Upload a PleX file to validate and analyze it"
    )
    @app_commands.describe(attachment="Your .plx / .plxcode / .attributes / .mf / .bun / .nude file")
    async def plex_upload(self, interaction: discord.Interaction, attachment: discord.Attachment):
        await interaction.response.defer(thinking=True)

        valid_exts = {".plx", ".plxcode", ".attributes", ".mf", ".bun", ".nude", ".Retard"}
        _, ext = os.path.splitext(attachment.filename.lower())

        if ext not in valid_exts:
            await interaction.followup.send(
                embed=make_error_embed(
                    f"Invalid file type `{ext}`.\n"
                    f"Accepted: `{', '.join(valid_exts)}`"
                )
            )
            return

        try:
            raw = await attachment.read()
            code = raw.decode("utf-8")
        except Exception as e:
            await interaction.followup.send(embed=make_error_embed(f"Could not read file: {e}"))
            return

        # Validate
        result = self.validator.validate(code)

        # Claude analysis
        prompt = (
            f"Analyze this PleX file (`{attachment.filename}`) and give a 2–4 sentence summary "
            f"of what it does and any issues:\n\n```PleX\n{code[:2000]}\n```"
        )
        analysis = await asyncio.to_thread(self._claude, prompt)

        color = 0x57F287 if result["valid"] else 0xFEE75C
        lines = [f"**File:** `{attachment.filename}`\n"]
        if not result["valid"]:
            lines += ["**❌ Errors:**"] + [f"`{e}`" for e in result["errors"]]
        if result["warnings"]:
            lines += ["**⚠️ Warnings:**"] + [f"`{w}`" for w in result["warnings"]]
        lines += [f"\n**🤖 Claude Analysis:**\n{analysis}"]

        embed = make_embed(
            title="🔍 PleX File Analysis",
            description="\n".join(lines)[:3900],
            color=color,
            footer=f"NCOM Systems · {attachment.filename}"
        )
        await interaction.followup.send(embed=embed)

    # ── Internal ──────────────────────────────────────────────────────────────
    def _claude(self, prompt: str) -> str:
        msg = self.ai.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=PLEX_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    def _generate_template(self, ext: str, name: str) -> str:
        templates = {
            "plx": (
                f"/!! {name}.plx — NCOM Systems PleX\n"
                f"/!! Created: {datetime.utcnow().strftime('%Y-%m-%d')}\n\n"
                f"Hail | @attributes\n"
                f"╰──➤ |~| {name}\n\n"
                f"Build | {name}\n"
                f"╰──➤ \n\n"
                f"Sign~!!"
            ),
            "plxcode": (
                f"/!! {name}.plxcode — NCOM Systems PleX\n"
                f"/!! Created: {datetime.utcnow().strftime('%Y-%m-%d')}\n\n"
                f"Hail | @attributes\n"
                f"╰──➤ |~| {name}\n\n"
                f"Build | {name}\n"
                f"╰──➤ \n\n"
                f"Sign~!!"
            ),
            "attributes": (
                f"/!! {name}.attributes — NCOM Systems Body File\n"
                f"/!! Address book for links, arguments, assets\n\n"
                f"@{name}\n"
                f"╰──➤ Author | [\"\"]\n"
                f"╰──➤ Version | 0.1.0\n"
                f"╰──➤ Created | {datetime.utcnow().strftime('%Y-%m-%d')}\n"
                f"╰──➤ Assets | [\"\"]\n"
                f"╰──➤ Links  | [\"\"]\n"
            ),
            "mf": (
                f"/!! {name}.mf — NCOM Systems Manifesto\n"
                f"/!! Zero-copy virtualization index\n\n"
                f"@manifest\n"
                f"╰──➤ Name    | {name}\n"
                f"╰──➤ Offset  | 0x0000\n"
                f"╰──➤ Length  | 0x0000\n"
                f"╰──➤ Hash    | [\"\"]\n"
            ),
            "bun": (
                f"/!! {name}.bun — NCOM Systems Bundle\n"
                f"/!! Compressed raw data stream\n\n"
                f"Bundle | {name}\n"
                f"╰──➤ Math | Logic\n"
                f"   ╰──➤ Argu~!!\n"
                f"      ╰──➤ [\"\"] | [\"\"]\n"
            ),
            "nude": (
                f"UI | .plx --Nude\n"
                f"/!! {name}.nude — NCOM Systems Nude Language\n\n"
                f"@User | action\n"
                f"╰──➤ Click | Button[A]\n"
                f"    ╰──➤ Pulse | n~ /f |~| @0xFAF1_NF-0\n"
            ),
        }
        return templates.get(ext, f"/!! {name}.{ext} — NCOM Systems PleX\n")


async def setup(bot: commands.Bot):
    await bot.add_cog(PlexCode(bot))
