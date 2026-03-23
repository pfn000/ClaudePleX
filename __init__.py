"""
cogs/github_backup.py
╰──➤ Sentient Backup System
    Hail | @Drive |~| @Google Drive
    GitHub → Google Drive protection layer
    If GitHub suspends your repo — we already saved it.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
import asyncio
import logging
import zipfile
import io
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from utils.drive_manager import DriveManager
from utils.embeds import make_embed, make_error_embed

log = logging.getLogger("ClaudePleX.Backup")

WATCHLIST_PATH = Path("data/watchlist.json")
BACKUP_CHANNEL_ID = int(os.getenv("BACKUP_CHANNEL_ID", "0"))


def load_watchlist() -> dict:
    if WATCHLIST_PATH.exists():
        with open(WATCHLIST_PATH) as f:
            return json.load(f)
    return {}


def save_watchlist(data: dict):
    WATCHLIST_PATH.parent.mkdir(exist_ok=True)
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(data, f, indent=2)


class GitHubBackup(commands.Cog):
    """
    Sentient Backup System
    ╰──➤ Watches GitHub repos
    ╰──➤ Backups to Google Drive on demand or schedule
    ╰──➤ Posts status to Discord
    """

    def __init__(self, bot: commands.Bot):
        self.bot      = bot
        self.drive    = DriveManager()
        self.watchlist: dict = load_watchlist()
        self.auto_backup.start()

    def cog_unload(self):
        self.auto_backup.cancel()

    # ── /backup_add ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="backup_add",
        description="Add a GitHub repo to the Sentient Backup watchlist"
    )
    @app_commands.describe(
        repo_url="GitHub repo URL (https://github.com/user/repo)",
        label="Short label for this repo (optional)"
    )
    async def backup_add(
        self,
        interaction: discord.Interaction,
        repo_url: str,
        label: str = ""
    ):
        await interaction.response.defer(ephemeral=True)

        repo_url = repo_url.rstrip("/")
        if "github.com" not in repo_url:
            await interaction.followup.send(
                embed=make_error_embed("Only GitHub URLs are supported."),
                ephemeral=True
            )
            return

        key = repo_url.split("github.com/")[-1].replace("/", "_")
        self.watchlist[key] = {
            "url":       repo_url,
            "label":     label or key,
            "added_by":  str(interaction.user),
            "added_at":  datetime.now(timezone.utc).isoformat(),
            "last_backup": None,
            "drive_id":  None,
        }
        save_watchlist(self.watchlist)

        embed = make_embed(
            title="📋 Repo Added to Watchlist",
            description=(
                f"**Repo:** `{repo_url}`\n"
                f"**Label:** `{label or key}`\n\n"
                f"Use `/backup_now` to immediately backup, or wait for auto-backup."
            ),
            color=0x57F287,
            footer="Sentient Backup System · NCOM Systems"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /backup_now ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="backup_now",
        description="Immediately backup a GitHub repo to Google Drive"
    )
    @app_commands.describe(repo_url="GitHub repo URL to backup (or 'all' for all watched repos)")
    async def backup_now(self, interaction: discord.Interaction, repo_url: str = "all"):
        await interaction.response.defer(thinking=True)

        if repo_url.lower() == "all":
            if not self.watchlist:
                await interaction.followup.send(
                    embed=make_error_embed("No repos in watchlist. Use `/backup_add` first.")
                )
                return
            results = []
            for key, entry in self.watchlist.items():
                r = await asyncio.to_thread(self._do_backup, key, entry)
                results.append(r)
            await self._send_backup_summary(interaction, results)
        else:
            key = repo_url.rstrip("/").split("github.com/")[-1].replace("/", "_")
            if key not in self.watchlist:
                # Auto-add it
                self.watchlist[key] = {
                    "url":       repo_url.rstrip("/"),
                    "label":     key,
                    "added_by":  str(interaction.user),
                    "added_at":  datetime.now(timezone.utc).isoformat(),
                    "last_backup": None,
                    "drive_id":  None,
                }
                save_watchlist(self.watchlist)

            result = await asyncio.to_thread(self._do_backup, key, self.watchlist[key])
            await self._send_backup_summary(interaction, [result])

    # ── /backup_list ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="backup_list",
        description="List all repos in the Sentient Backup watchlist"
    )
    async def backup_list(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not self.watchlist:
            await interaction.followup.send(
                embed=make_embed(
                    title="📋 Backup Watchlist",
                    description="No repos added yet. Use `/backup_add` to protect a repo.",
                    color=0xFEE75C
                )
            )
            return

        lines = []
        for i, (key, entry) in enumerate(self.watchlist.items(), 1):
            last = entry.get("last_backup") or "Never"
            if last != "Never":
                last = last[:10]  # Date only
            drive_link = (
                f"[View on Drive](https://drive.google.com/drive/folders/{entry['drive_id']})"
                if entry.get("drive_id") else "Not backed up yet"
            )
            lines.append(
                f"**{i}. `{entry['label']}`**\n"
                f"  ╰──➤ URL: {entry['url']}\n"
                f"  ╰──➤ Last backup: `{last}`\n"
                f"  ╰──➤ Drive: {drive_link}\n"
            )

        embed = make_embed(
            title=f"📋 Backup Watchlist — {len(self.watchlist)} repo(s)",
            description="\n".join(lines)[:3900],
            color=0x5865F2,
            footer="Sentient Backup System · NCOM Systems"
        )
        await interaction.followup.send(embed=embed)

    # ── /backup_remove ────────────────────────────────────────────────────────
    @app_commands.command(
        name="backup_remove",
        description="Remove a repo from the backup watchlist"
    )
    @app_commands.describe(label="Repo label or full URL to remove")
    async def backup_remove(self, interaction: discord.Interaction, label: str):
        await interaction.response.defer(ephemeral=True)

        # Find by label or URL key
        key_to_remove = None
        for key, entry in self.watchlist.items():
            if entry["label"] == label or entry["url"] == label or key == label:
                key_to_remove = key
                break

        if not key_to_remove:
            await interaction.followup.send(
                embed=make_error_embed(f"Repo `{label}` not found in watchlist."),
                ephemeral=True
            )
            return

        removed = self.watchlist.pop(key_to_remove)
        save_watchlist(self.watchlist)

        await interaction.followup.send(
            embed=make_embed(
                title="🗑️ Repo Removed",
                description=f"Removed `{removed['label']}` from the watchlist.",
                color=0xED4245
            ),
            ephemeral=True
        )

    # ── /backup_status ────────────────────────────────────────────────────────
    @app_commands.command(
        name="backup_status",
        description="Check the health of the Sentient Backup System"
    )
    async def backup_status(self, interaction: discord.Interaction):
        await interaction.response.defer()

        drive_ok = await asyncio.to_thread(self.drive.test_connection)
        total    = len(self.watchlist)
        backed   = sum(1 for e in self.watchlist.values() if e.get("last_backup"))

        color = 0x57F287 if drive_ok else 0xED4245
        status_icon = "✅" if drive_ok else "❌"

        embed = make_embed(
            title="🛡️ Sentient Backup System Status",
            description=(
                f"**Google Drive:** {status_icon} {'Connected' if drive_ok else 'Disconnected'}\n"
                f"**Auto-backup:** ✅ Running (every 6h)\n"
                f"**Watched repos:** `{total}`\n"
                f"**Repos backed up:** `{backed}/{total}`\n\n"
                f"```\nHail | @Drive |~| @Google Drive\n"
                f"╰──➤ Status | {'Online' if drive_ok else 'Offline'}\n"
                f"╰──➤ Repos  | {total}\n"
                f"╰──➤ Backed | {backed}\n```"
            ),
            color=color,
            footer="Sentient Backup System · NCOM Systems"
        )
        await interaction.followup.send(embed=embed)

    # ── Scheduled auto-backup task ────────────────────────────────────────────
    @tasks.loop(hours=6)
    async def auto_backup(self):
        if not self.watchlist:
            return

        log.info(f"[Auto-Backup] Starting scheduled backup for {len(self.watchlist)} repo(s)...")

        results = []
        for key, entry in self.watchlist.items():
            r = await asyncio.to_thread(self._do_backup, key, entry)
            results.append(r)
            await asyncio.sleep(2)  # rate limit courtesy

        # Post to backup channel if configured
        channel = self.bot.get_channel(BACKUP_CHANNEL_ID)
        if channel and BACKUP_CHANNEL_ID:
            ok    = sum(1 for r in results if r["success"])
            fail  = len(results) - ok
            color = 0x57F287 if fail == 0 else 0xFEE75C

            embed = make_embed(
                title="🔄 Auto-Backup Complete",
                description=(
                    f"**Repos processed:** `{len(results)}`\n"
                    f"**✅ Success:** `{ok}` | **❌ Failed:** `{fail}`\n\n"
                    + "\n".join(
                        f"{'✅' if r['success'] else '❌'} `{r['label']}`"
                        + (f" → [{r.get('drive_id', '')}]" if r["success"] else f" — {r.get('error', '')}")
                        for r in results
                    )
                ),
                color=color,
                footer=f"Next auto-backup in 6h · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )
            await channel.send(embed=embed)

        log.info(f"[Auto-Backup] Done. {ok}/{len(results)} succeeded.")

    @auto_backup.before_loop
    async def before_auto_backup(self):
        await self.bot.wait_until_ready()

    # ── Core backup logic ─────────────────────────────────────────────────────
    def _do_backup(self, key: str, entry: dict) -> dict:
        """Download ZIP from GitHub, upload to Google Drive."""
        import urllib.request

        repo_url    = entry["url"]
        label       = entry["label"]
        timestamp   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        zip_name    = f"{key}_{timestamp}.zip"
        # GitHub provides a ZIP of the default branch
        zip_url     = repo_url.rstrip("/") + "/archive/refs/heads/main.zip"
        zip_url_alt = repo_url.rstrip("/") + "/archive/refs/heads/master.zip"

        tmpdir = tempfile.mkdtemp()
        zip_path = os.path.join(tmpdir, zip_name)

        try:
            # Try main branch first, fall back to master
            downloaded = False
            for url in [zip_url, zip_url_alt]:
                try:
                    headers = {"User-Agent": "ClaudePleX-Bot/1.0"}
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        with open(zip_path, "wb") as f:
                            f.write(resp.read())
                    downloaded = True
                    log.info(f"[Backup] Downloaded {label} from {url}")
                    break
                except Exception:
                    continue

            if not downloaded:
                raise RuntimeError(f"Could not download {repo_url} (tried main + master branches)")

            # Upload to Google Drive
            folder_id = self.drive.ensure_folder(f"ClaudePleX-Backups/{label}")
            file_id   = self.drive.upload_file(zip_path, zip_name, folder_id)

            # Update watchlist entry
            self.watchlist[key]["last_backup"] = datetime.now(timezone.utc).isoformat()
            self.watchlist[key]["drive_id"]    = folder_id
            save_watchlist(self.watchlist)

            return {
                "success":  True,
                "label":    label,
                "file_id":  file_id,
                "drive_id": folder_id,
                "zip_name": zip_name,
            }

        except Exception as e:
            log.error(f"[Backup] Failed {label}: {e}")
            return {"success": False, "label": label, "error": str(e)}

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def _send_backup_summary(self, interaction: discord.Interaction, results: list):
        ok   = sum(1 for r in results if r["success"])
        fail = len(results) - ok
        color = 0x57F287 if fail == 0 else (0xFEE75C if ok > 0 else 0xED4245)

        lines = []
        for r in results:
            if r["success"]:
                drive_link = f"https://drive.google.com/drive/folders/{r['drive_id']}"
                lines.append(f"✅ **`{r['label']}`** → [Google Drive]({drive_link})")
            else:
                lines.append(f"❌ **`{r['label']}`** — `{r.get('error', 'Unknown error')}`")

        embed = make_embed(
            title="🛡️ Backup Complete",
            description=(
                f"**{ok}/{len(results)} repos backed up**\n\n"
                + "\n".join(lines) +
                "\n\n```PleX\nHail | @Drive\n"
                "╰──➤ |~| @Google.Drive\n"
                f"╰──➤ Status | {'Success' if fail == 0 else 'Partial'}\n```"
            ),
            color=color,
            footer="Sentient Backup System · NCOM Systems · ClaudePleX"
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GitHubBackup(bot))
