#!/usr/bin/env python3
"""
Slack Daemon: Robust & Debug-Ready (Bolt + Socket Mode).
AppImage Safe: Uses dynamic paths for heartbeat.
"""
import os
import sys
import time
import json
import logging
import threading
import requests
from pathlib import Path
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='🟣 [SLACK] %(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
logger.info("🚀 Script started. Initializing...")

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
GENESYS_URL = os.getenv("GENESYS_ENGINE_URL", "http://localhost:5000")

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    logger.error("❌ CRITICAL: Slack tokens missing in .env")
    sys.exit(1)

logger.info(f"✅ Tokens validated.")

# ==============================================================================
# HEARTBEAT
# ==============================================================================
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
    logger.info(f"❤️ Starting Heartbeat for {daemon_name} -> {status_file}")

    def loop():
        while True:
            try:
                data = {"daemon": daemon_name, "status": "running", "pid": os.getpid(), "timestamp": time.time()}
                status_file.parent.mkdir(parents=True, exist_ok=True)
                with open(status_file, 'w') as f:
                    json.dump(data, f)
                time.sleep(5)
            except Exception as e:
                logger.error(f"❌ Heartbeat Error: {e}", exc_info=True)
                time.sleep(5)
    
    t = threading.Thread(target=loop, daemon=True, name="HeartbeatThread")
    t.start()

start_heartbeat("slack")

try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
except ImportError as e:
    logger.error(f"❌ FAILED to import slack_bolt. Run: pip install slack-bolt slack-sdk")
    sys.exit(1)

app = App(token=SLACK_BOT_TOKEN)

def send_to_lmim(user_id, text, channel_id, ts):
    payload = {"sender": user_id, "body": text, "channel_id": channel_id, "thread_ts": ts}
    url = f"{GENESYS_URL}/webhooks/slack/incoming"
    try:
        resp = requests.post(url, json=payload, timeout=180)
        resp.raise_for_status()
        return resp.json().get("reply")
    except Exception as e:
        logger.error(f"❌ LMIM Error: {e}")
        return None

@app.event("app_mention")
def handle_mention(event, say):
    try:
        user = event.get("user")
        text = event.get("text")
        channel = event.get("channel")
        ts = event.get("ts")
        logger.info(f"📩 Mention Received from @{user}")
        reply = send_to_lmim(f"slack_{user}", text, channel, ts)
        if reply:
            say(text=reply, thread_ts=ts)
        else:
            say(text=":warning: Sorry, I couldn't process that request.", thread_ts=ts)
    except Exception as e:
        logger.error(f"💥 Error in handle_mention: {e}", exc_info=True)

@app.event("message")
def handle_dm(message, client):
    try:
        if message.get("bot_id") or message.get("channel_type") != "im":
            return
        user = message.get("user")
        text = message.get("text")
        channel = message.get("channel")
        ts = message.get("ts")
        if not text: return
        logger.info(f"📩 DM Received from @{user}")
        reply = send_to_lmim(f"slack_{user}", text, channel, ts)
        if reply:
            client.chat_postMessage(channel=channel, text=reply, thread_ts=ts)
    except Exception as e:
        logger.error(f"💥 Error in handle_dm: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        logger.info("="*50)
        logger.info("🟣 STARTING SLACK DAEMON (Socket Mode)")
        logger.info("="*50)
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        handler.start()
    except KeyboardInterrupt:
        logger.info("🛑 Stopped by user.")
    except Exception as e:
        logger.error(f"💥 CRITICAL: Daemon crashed: {e}", exc_info=True)
        # Write crash to file for debugging
        crash_file = Path(os.getenv('LMIM_DATA_DIR', '.')) / "logs" / "slack_crash.log"
        crash_file.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_file, 'a') as f:
            f.write(f"{time.ctime()}: {e}\n")
        sys.exit(1)
