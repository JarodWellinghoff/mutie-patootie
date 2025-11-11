import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import os
import sys
from collections import defaultdict
from dotenv import load_dotenv
import asyncio
from aiohttp import web
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Force unbuffered output
os.environ["PYTHONUNBUFFERED"] = "1"

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Track mute start times: {user_id: datetime}
mute_times = {}
# Track TTS activity: {user_id: datetime of last TTS}
tts_activity = {}

# Configuration
MUTE_TIMEOUT_MINUTES = int(os.getenv("MUTE_TIMEOUT_MINUTES", "30"))
# Allow overriding initial check interval via env, default to 1s
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "1"))

# Optional: set TEST_GUILD_ID in env for faster slash command sync during testing
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")
TEST_GUILD = discord.Object(id=int(TEST_GUILD_ID)) if TEST_GUILD_ID else None


async def _health(request):
    logger.debug(f"Health check from {request.remote}")
    return web.Response(text="ok")


async def start_health_app():
    app = web.Application()
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8000")))
    await site.start()


@bot.event
async def on_ready():
    logger.info(f"✅ {bot.user} is now running!")
    logger.info(f"📊 Connected to {len(bot.guilds)} guild(s)")
    for guild in bot.guilds:
        logger.info(f"   - {guild.name} (ID: {guild.id})")

    check_muted_users.start()
    logger.info(
        f"⏰ Started mute checker (interval: {CHECK_INTERVAL_SECONDS}s, timeout: {MUTE_TIMEOUT_MINUTES}min)"
    )

    # Sync slash commands (guild-scoped if TEST_GUILD provided for faster availability)
    try:
        if TEST_GUILD:
            bot.tree.copy_global_to(guild=TEST_GUILD)
            synced = await bot.tree.sync(guild=TEST_GUILD)
            logger.info(f"✅ Synced {len(synced)} guild commands to TEST_GUILD")
        else:
            synced = await bot.tree.sync()
            logger.info(f"✅ Synced {len(synced)} global commands")
    except Exception as e:
        logger.error(f"❌ Failed to sync commands: {e}")


@bot.event
async def on_voice_state_update(member, before, after):
    """Track when users get muted or unmuted"""

    # User joined voice or changed mute state
    if after.channel:
        # User is now muted (server mute or self mute)
        if (after.mute or after.self_mute) and not (before.mute or before.self_mute):
            mute_times[member.id] = datetime.now()
            mute_type = "server-muted" if after.mute else "self-muted"
            logger.info(
                f"🔇 {member.name} {mute_type} in {after.channel.name} at {datetime.now().strftime('%H:%M:%S')}"
            )

        # User is now unmuted
        elif not (after.mute or after.self_mute) and (before.mute or before.self_mute):
            if member.id in mute_times:
                duration = datetime.now() - mute_times[member.id]
                del mute_times[member.id]
                logger.info(
                    f"🔊 {member.name} unmuted after {duration.total_seconds()/60:.1f} minutes"
                )

    # User left voice channel
    elif before.channel and not after.channel:
        if member.id in mute_times:
            duration = datetime.now() - mute_times[member.id]
            del mute_times[member.id]
            logger.info(
                f"👋 {member.name} left voice (was muted for {duration.total_seconds()/60:.1f} minutes)"
            )
        if member.id in tts_activity:
            del tts_activity[member.id]


@bot.event
async def on_message(message):
    """Track TTS messages to exempt users from auto-disconnect"""
    if message.tts and message.author.voice:
        tts_activity[message.author.id] = datetime.now()
        logger.info(
            f"📢 {message.author.name} sent TTS message in #{message.channel.name}"
        )


@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def check_muted_users():
    """Periodically check and disconnect users who have been muted too long"""
    if not mute_times:
        return  # Skip if no muted users

    now = datetime.now()
    timeout_threshold = timedelta(minutes=MUTE_TIMEOUT_MINUTES)
    tts_grace_period = timedelta(minutes=5)  # Consider recent TTS activity

    logger.debug(
        f"🔍 Checking {len(mute_times)} muted user(s) at {now.strftime('%H:%M:%S')}"
    )
    users_to_remove = []

    # Iterate over a snapshot to avoid "dictionary changed size during iteration"
    for user_id, mute_start in list(mute_times.items()):
        # Check if user has recent TTS activity
        last_tts = tts_activity.get(user_id)
        if last_tts and (now - last_tts) < tts_grace_period:
            continue  # Skip users with recent TTS activity

        # Check if mute timeout exceeded
        mute_duration = now - mute_start
        # Find the user in all guilds
        for guild in bot.guilds:
            member = guild.get_member(user_id)
            if member and member.voice:
                if mute_duration > timeout_threshold:
                    try:
                        await member.move_to(None)
                        logger.info(
                            f"⏰ Auto-disconnected {member.name} after {mute_duration.total_seconds()/60:.1f} minutes muted"
                        )
                        users_to_remove.append(user_id)
                    except discord.Forbidden:
                        logger.error(
                            f"❌ Missing permissions to disconnect {member.name}"
                        )
                    except Exception as e:
                        logger.error(f"❌ Error disconnecting {member.name}: {e}")

    # Clean up disconnected users
    for user_id in users_to_remove:
        if user_id in mute_times:
            del mute_times[user_id]
        if user_id in tts_activity:
            del tts_activity[user_id]


@check_muted_users.before_loop
async def before_check():
    await bot.wait_until_ready()


# Slash commands


@bot.tree.command(name="set-timeout", description="Set mute timeout in minutes")
@app_commands.describe(minutes="Mute timeout in minutes")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def set_timeout_slash(
    interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 720]
):
    global MUTE_TIMEOUT_MINUTES
    old_timeout = MUTE_TIMEOUT_MINUTES
    MUTE_TIMEOUT_MINUTES = minutes
    logger.info(
        f"⚙️ {interaction.user.name} changed timeout: {old_timeout} → {minutes} minutes"
    )
    await interaction.response.send_message(
        f"Mute timeout set to {minutes} minutes.", ephemeral=True
    )


@bot.tree.command(name="set-interval", description="Set check interval in seconds")
@app_commands.describe(seconds="Loop interval in seconds")
@app_commands.default_permissions(administrator=True)
@app_commands.guild_only()
async def set_interval_slash(
    interaction: discord.Interaction, seconds: app_commands.Range[int, 1, 3600]
):
    global CHECK_INTERVAL_SECONDS
    old_interval = CHECK_INTERVAL_SECONDS
    CHECK_INTERVAL_SECONDS = seconds
    try:
        # Adjust the running loop interval dynamically
        check_muted_users.change_interval(seconds=CHECK_INTERVAL_SECONDS)
        logger.info(
            f"⚙️ {interaction.user.name} changed check interval: {old_interval} → {seconds} seconds"
        )
        msg = f"Check interval set to {CHECK_INTERVAL_SECONDS} seconds."
    except Exception as e:
        logger.error(f"❌ Failed to change loop interval: {e}")
        msg = f"Failed to change loop interval: {e}"
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="mute-status", description="Show currently tracked muted users")
@app_commands.guild_only()
async def mute_status_slash(interaction: discord.Interaction):
    logger.info(f"📋 {interaction.user.name} requested mute status")

    if not mute_times:
        await interaction.response.send_message(
            "No users are currently being tracked as muted.", ephemeral=True
        )
        return

    now = datetime.now()
    status = "**Currently Muted Users:**\n"
    # Iterate over a snapshot to avoid concurrent modification issues
    for user_id, mute_start in list(mute_times.items()):
        member = interaction.guild.get_member(user_id) if interaction.guild else None
        if member:
            duration = now - mute_start
            minutes = duration.total_seconds() / 60
            last_tts = tts_activity.get(user_id)
            has_recent_tts = last_tts is not None and (now - last_tts) < timedelta(
                minutes=5
            )
            tts_indicator = " (TTS active)" if has_recent_tts else ""
            status += f"- {member.name}: {minutes:.1f} minutes{tts_indicator}\n"

    # Defer if large; otherwise send ephemeral
    if len(status) > 1800:
        await interaction.response.send_message(
            "Sending muted user list...", ephemeral=True
        )
        await interaction.followup.send(status, ephemeral=True)
    else:
        await interaction.response.send_message(status, ephemeral=True)


async def main():
    """Run both the health server and Discord bot"""
    logger.info("🚀 Starting Discord Mute Monitor Bot...")

    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        logger.error("❌ ERROR: DISCORD_TOKEN environment variable not set")
        raise ValueError("DISCORD_TOKEN environment variable not set")

    logger.info(f"📝 Configuration:")
    logger.info(f"   - Mute timeout: {MUTE_TIMEOUT_MINUTES} minutes")
    logger.info(f"   - Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    logger.info(f"   - Health port: {os.getenv('PORT', '8000')}")

    # Start health check server for Koyeb
    await start_health_app()
    logger.info(f"✅ Health server started on port {os.getenv('PORT', '8000')}")

    # Start Discord bot
    logger.info("🤖 Connecting to Discord...")
    await bot.start(TOKEN)


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Discord Mute Monitor Bot v1.0")
    logger.info("=" * 50)
    asyncio.run(main())
