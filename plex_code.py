"""
cogs/claude_chat.py
╰──➤ Claude AI chat cog — PleX-aware, thread-based conversations
"""

import discord
from discord import app_commands
from discord.ext import commands
import anthropic
import os
import asyncio
import logging
from collections import defaultdict
from utils.plex_context import PLEX_SYSTEM_PROMPT
from utils.embeds import make_embed, make_error_embed

log = logging.getLogger("ClaudePleX.Chat")

CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_HISTORY  = 20       # messages kept per thread
MAX_TOKENS   = 2048


class ConversationManager:
    """In-memory conversation store, keyed by channel/thread ID."""

    def __init__(self):
        self._store: dict[int, list[dict]] = defaultdict(list)

    def add(self, channel_id: int, role: str, content: str):
        history = self._store[channel_id]
        history.append({"role": role, "content": content})
        # Trim to last MAX_HISTORY messages
        if len(history) > MAX_HISTORY:
            self._store[channel_id] = history[-MAX_HISTORY:]

    def get(self, channel_id: int) -> list[dict]:
        return self._store[channel_id]

    def clear(self, channel_id: int):
        self._store[channel_id] = []


class ClaudeChat(commands.Cog):
    """Chat with Claude AI — PleX-aware, persistent threads."""

    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self.ai    = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.convs = ConversationManager()

    # ── /chat ─────────────────────────────────────────────────────────────────
    @app_commands.command(name="chat", description="Chat with ClaudePleX AI")
    @app_commands.describe(message="Your message to Claude")
    async def chat(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(thinking=True)

        channel_id = interaction.channel_id
        self.convs.add(channel_id, "user", message)

        try:
            response = await asyncio.to_thread(
                self._call_claude,
                channel_id,
            )
            self.convs.add(channel_id, "assistant", response)

            # Split long responses
            chunks = self._split(response, 1900)
            embed = make_embed(
                title="🤖 ClaudePleX",
                description=chunks[0],
                color=0x5865F2,
                footer=f"Model: {CLAUDE_MODEL} | /chat_clear to reset"
            )
            await interaction.followup.send(embed=embed)

            for chunk in chunks[1:]:
                await interaction.channel.send(
                    embed=make_embed(description=chunk, color=0x5865F2)
                )

        except anthropic.APIError as e:
            log.error(f"Anthropic API error: {e}")
            await interaction.followup.send(
                embed=make_error_embed(f"Claude API error: {e}")
            )

    # ── /chat_clear ───────────────────────────────────────────────────────────
    @app_commands.command(name="chat_clear", description="Clear conversation history in this channel")
    async def chat_clear(self, interaction: discord.Interaction):
        self.convs.clear(interaction.channel_id)
        await interaction.response.send_message(
            embed=make_embed("🧹 Conversation cleared", color=0x57F287),
            ephemeral=True
        )

    # ── /ask_plex ─────────────────────────────────────────────────────────────
    @app_commands.command(name="ask_plex", description="Ask Claude specifically about PleX code")
    @app_commands.describe(question="Your PleX question")
    async def ask_plex(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(thinking=True)

        focused_prompt = (
            f"The user has a question specifically about PleX code / NCOM Systems language.\n"
            f"Question: {question}"
        )
        self.convs.add(interaction.channel_id, "user", focused_prompt)

        try:
            response = await asyncio.to_thread(self._call_claude, interaction.channel_id)
            self.convs.add(interaction.channel_id, "assistant", response)

            embed = make_embed(
                title="🧠 PleX AI Answer",
                description=response[:1900],
                color=0xFEE75C,
                footer="NCOM Systems PleX · Claude AI"
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(embed=make_error_embed(str(e)))

    # ── Internal ──────────────────────────────────────────────────────────────
    def _call_claude(self, channel_id: int) -> str:
        history = self.convs.get(channel_id)
        msg = self.ai.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=PLEX_SYSTEM_PROMPT,
            messages=history,
        )
        return msg.content[0].text

    @staticmethod
    def _split(text: str, limit: int) -> list[str]:
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            chunks.append(text[:limit])
            text = text[limit:]
        return chunks


async def setup(bot: commands.Bot):
    await bot.add_cog(ClaudeChat(bot))
