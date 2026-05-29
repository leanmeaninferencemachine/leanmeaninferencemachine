#!/usr/bin/env python3
"""
Telegram Daemon: Robust Polling with Aggressive Debug Logging.
AppImage Safe: Uses dynamic paths for heartbeat.
"""
import os
import sys
import json
import logging
import time
import asyncio
import requests
import threading
from pathlib import Path
from dotenv import load_dotenv

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
                data = {"daemon": daemon_name, "status": "running", "pid": os.getpid(), "timestamp": time.time()}
                status_file.parent.mkdir(parents=True, exist_ok=True)
                with open(status_file, 'w') as f:
                    json.dump(data, f)
                time.sleep(5)
            except Exception as e:
                print(f"❌ [{daemon_name.upper()}] Heartbeat Error: {e}", flush=True)
                pass
    
    t = threading.Thread(target=loop, daemon=True)
    t.start()

start_heartbeat("telegram")

class FlushHandler(logging.StreamHandler):
    def emit(self, record):
        msg = self.format(record)
        print(msg, flush=True)

logger = logging.getLogger("TG_DAEMON")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = FlushHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('🔵 [TG] %(levelname)s | %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

# === CONFIG ===
TG_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_POLL_INTERVAL = 2 

if not TG_BOT_TOKEN:
    logger.error("❌ CRITICAL: TELEGRAM_BOT_TOKEN is missing in .env!")
    sys.exit(1)

# 🔥 FIX: Ensure no whitespace in token and correct URL format
TG_BOT_TOKEN = TG_BOT_TOKEN.strip()
TG_API_URL = f"https://api.telegram.org/bot{TG_BOT_TOKEN}" # Removed spaces

logger.info(f"🌐 API URL: {TG_API_URL}/getMe")

def send_message(chat_id, text, reply_to_message_id=None):
    if len(text) > 4000:
        text = text[:3990] + "\n\n... (truncated)"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to_message_id:
        params["reply_to_message_id"] = reply_to_message_id
    try:
        resp = requests.post(f"{TG_API_URL}/sendMessage", json=params)
        resp.raise_for_status()
        logger.info(f"✅ Message sent to {chat_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send message: {e}")

def get_me():
    logger.info("🔍 Testing connection to Telegram API...")
    try:
        url = f"{TG_API_URL}/getMe"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get('ok'):
            username = data['result'].get('username', 'NoUsername')
            logger.info(f"✅ SUCCESS! Connected to Bot: @{username}")
            return True
        else:
            logger.error(f"❌ API Error: {data}")
            return False
    except Exception as e:
        logger.error(f"❌ Exception: {e}")
        return False

def get_updates(offset=None):
    params = {"offset": offset, "timeout": 5, "allowed_updates": ["message"]}
    try:
        url = f"{TG_API_URL}/getUpdates"
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"⚠️ Polling returned status {resp.status_code}")
            return []
        return resp.json().get("result", [])
    except Exception as e:
        logger.error(f"❌ Polling error: {e}")
        return []

def send_to_engine(user_id, text, chat_id, message_id, user_name):
    url = "http://localhost:5000/webhooks/telegram/incoming"
    payload = {"user_id": user_id, "text": text, "chat_id": chat_id, "message_id": message_id, "user_name": user_name}
    try:
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json().get("reply")
    except Exception as e:
        logger.error(f"❌ Engine connection failed: {e}")
        return None

async def process_telegram_message(msg_data):
    message = msg_data.get("message")
    if not message: return
    chat_id = message.get("chat", {}).get("id")
    user = message.get("from", {})
    user_id = f"tg_{user.get('id')}"
    user_name = user.get("first_name", "Unknown")
    text = message.get("text", "")
    message_id = message.get("message_id")
    if not text: return
    logger.info(f"💬 MSG from {user_name}: '{text[:40]}...'")
    reply = send_to_engine(user_id, text, chat_id, message_id, user_name)
    if reply:
        send_message(chat_id, reply, reply_to_message_id=message_id)

async def telegram_listener_loop():
    global last_update_id
    last_update_id = 0
    logger.info("👂 Starting Polling Loop...")
    while True:
        try:
            updates = get_updates(offset=last_update_id + 1)
            if updates:
                for update in updates:
                    last_update_id = update["update_id"]
                    await process_telegram_message(update)
            else:
                await asyncio.sleep(TG_POLL_INTERVAL)
        except Exception as e:
            logger.error(f"💥 Loop crash: {e}", exc_info=True)
            await asyncio.sleep(5)

if __name__ == "__main__":
    print("="*50)
    print("🚀 TELEGRAM DAEMON STARTING (DEBUG MODE)")
    print("="*50)
    if not get_me():
        print("❌ FATAL: Connection test failed. Exiting.")
        sys.exit(1)
    print("✅ Connection OK. Entering Polling Loop...")
    try:
        asyncio.run(telegram_listener_loop())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
