#!/usr/bin/env python3
"""
Discord Daemon: Listens for DMs and Mentions, replies via LMIM.
AppImage Safe: Uses dynamic paths for heartbeat.
"""
import os
import sys
import logging
import time
import requests
import threading
import json  # ← ADD THIS LINE
from pathlib import Path
from dotenv import load_dotenv
import discord
from discord.ext import commands

# === ❤️ HEARTBEAT: AppImage Safe ===
def start_heartbeat(daemon_name: str):
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        data_root = Path(env_path)
    else:
        current_script = Path(__file__).resolve()
        if current_script.parent.name in ['daemons', 'scripts']:
            data_root = current_script.parent.parent / "data"
        else:
            data_root = current_script.parent / "data"
    
    status_file = data_root / f"daemon_status_{daemon_name}.json"
    print(f"✅ [{daemon_name.upper()}] Heartbeat initialized. Writing to: {status_file}", flush=True)

    def loop():
        while True:
            try:
                data = {
                    "daemon": daemon_name,
                    "status": "running",
                    "pid": os.getpid(),
                    "timestamp": time.time()
                }
                status_file.parent.mkdir(parents=True, exist_ok=True)
                with open(status_file, 'w') as f:
                    json.dump(data, f)
                time.sleep(5)
            except Exception as e:
                print(f"❌ [{daemon_name.upper()}] Heartbeat Error: {e}", flush=True)
                pass
    
    t = threading.Thread(target=loop, daemon=True)
    t.start()

start_heartbeat("discord")

# Setup Logging
logging.basicConfig(level=logging.INFO, format='🔵 [DISCORD] %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

# Config
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GENESYS_URL = os.getenv("GENESYS_ENGINE_URL", "http://localhost:5000")

if not DISCORD_TOKEN:
    logger.error("❌ Missing DISCORD_BOT_TOKEN")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

def send_to_lmim(user_id, text, channel_id):
    payload = {
        "sender": str(user_id),
        "subject": "Discord Message",
        "body": text,
        "platform": "discord",
        "channel_id": channel_id
    }
    try:
        resp = requests.post(f"{GENESYS_URL}/webhooks/discord/incoming", json=payload, timeout=180)
        resp.raise_for_status()
        return resp.json().get("reply")
    except Exception as e:
        logger.error(f"❌ LMIM error: {e}")
        return None

@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    is_mentioned = bot.user in message.mentions
    is_dm = isinstance(message.channel, discord.DMChannel)

    if is_mentioned or is_dm:
        user = message.author
        text = message.content
        
        if is_mentioned:
            text = text.replace(f"<@{bot.user.id}>", "").strip()
        
        if not text:
            return

        logger.info(f"📩 Msg from {user} ({'DM' if is_dm else 'Mention'}): {text[:50]}...")
        
        async with message.channel.typing():
            reply = send_to_lmim(user.id, text, message.channel.id)
            
            if reply:
                logger.info(f"💬 Reply generated ({len(reply)} chars). Sending to Discord...")
                if len(reply) > 2000:
                    reply = reply[:1990] + "..."
                await message.reply(reply, mention_author=False)
                logger.info("✅ Reply sent successfully.")
            else:
                await message.reply("⚠️ Error processing request.")

    await bot.process_commands(message)
# At the bottom of discord_daemon.py (and slack_daemon.py if needed):
if __name__ == "__main__":
    try:
        logger.info("🚀 Starting daemon...")
        # ... existing startup code ...
        bot.run(DISCORD_TOKEN)  # or handler.start() for Slack
    except Exception as e:
        logger.error(f"💥 Daemon crashed on startup: {e}", exc_info=True)
        # Write crash to a file for debugging
        crash_file = Path(os.getenv('LMIM_DATA_DIR', '.')) / "logs" / "discord_crash.log"
        crash_file.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_file, 'a') as f:
            f.write(f"{time.ctime()}: {e}\n")
        sys.exit(1)
