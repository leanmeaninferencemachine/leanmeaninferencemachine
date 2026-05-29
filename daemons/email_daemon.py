#!/usr/bin/env python3
"""
Email Daemon: Fast Polling (15s) + Robust Fetch + Smart Filters.
AppImage Safe: Uses dynamic paths for heartbeat.
"""
import os
import sys
import logging
import time
import requests
import imaplib
import email
import smtplib
import threading
import json
from pathlib import Path
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

start_heartbeat("email")

class FlushHandler(logging.StreamHandler):
    def emit(self, record):
        msg = self.format(record)
        print(msg, flush=True)

logger = logging.getLogger("EMAIL_DAEMON")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = FlushHandler()
    ch.setFormatter(logging.Formatter('📧 [EMAIL] %(levelname)s | %(message)s'))
    logger.addHandler(ch)

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

# === CONFIG ===
EMAIL_ADDR = os.getenv("SMTP_USER")
EMAIL_PASS = os.getenv("SMTP_PASS")
IMAP_SERVER = os.getenv("EMAIL_IMAP_SERVER", "imap.dreamhost.com")
IMAP_PORT = int(os.getenv("EMAIL_IMAP_PORT", "993"))
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.dreamhost.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
FROM_NAME = os.getenv("SMTP_FROM_NAME", "LMIM AI")
GENESYS_URL = os.getenv("GENESYS_ENGINE_URL", "http://localhost:5000")

POLL_INTERVAL = 15 
IGNORE_SENDERS = ["noreply@", "no-reply@", "donotreply@", "automated@", "mailer-daemon@", "postmaster@", "github.com", "notifications@", "dreamhost.com"]

if not EMAIL_ADDR or not EMAIL_PASS:
    logger.error("❌ Missing SMTP_USER or SMTP_PASS in .env")
    sys.exit(1)

def should_ignore(sender):
    return any(ignore in sender.lower() for ignore in IGNORE_SENDERS)

def send_email_reply(to_addr, subject_original, reply_text):
    try:
        msg = MIMEMultipart()
        msg['From'] = f"{FROM_NAME} <{EMAIL_ADDR}>"
        msg['To'] = to_addr
        msg['Subject'] = f"Re: {subject_original}"
        msg['Reply-To'] = EMAIL_ADDR
        
        body = f"{reply_text}\n\n--\nSent by {FROM_NAME}\nExecutive Assistant to Andrés Santos"
        msg.attach(MIMEText(body, 'plain'))
        
        logger.debug(f"📤 Connecting to SMTP {SMTP_SERVER}:{SMTP_PORT}...")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_ADDR, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        logger.info(f"✅ Email sent to {to_addr}")
        return True
    except Exception as e:
        logger.error(f"❌ SMTP Error: {e}")
        return False

def fetch_and_process_email(mail, msg_id):
    try:
        res, data = mail.fetch(msg_id, "(RFC822)")
        raw_email = None
        for part in data:
            if isinstance(part, tuple):
                for item in part:
                    if isinstance(item, bytes) and len(item) > 100:
                        raw_email = item
                        break
            elif isinstance(part, bytes) and len(part) > 100:
                raw_email = part
                break
        
        if not raw_email:
            logger.warning(f"⚠️ Could not extract body for msg {msg_id}")
            mail.store(msg_id, '+FLAGS', '\\Seen')
            return

        msg = email.message_from_bytes(raw_email)
        sender = email.utils.parseaddr(msg['From'])[1]
        subject = msg['Subject'] or "(No Subject)"
        
        if should_ignore(sender):
            logger.debug(f"⏭️ Ignored (Filter): {sender}")
            mail.store(msg_id, '+FLAGS', '\\Seen')
            return

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                    try:
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
                    except: pass
        else:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
            
        if not body or len(body.strip()) < 10:
            mail.store(msg_id, '+FLAGS', '\\Seen')
            return

        logger.info(f"📩 LIVE EMAIL: From={sender}, Sub='{subject[:30]}...'")
        
        payload = {"sender": sender, "subject": subject, "body": body, "message_id": str(msg_id)}
        url = f"{GENESYS_URL}/webhooks/email/incoming"
        
        resp = requests.post(url, json=payload, timeout=100)
        resp.raise_for_status()
        reply_text = resp.json().get("reply")
        
        if reply_text:
            logger.info(f"💬 Reply generated.")
            success = send_email_reply(sender, subject, reply_text)
            if success:
                mail.store(msg_id, '+FLAGS', '\\Seen')
            else:
                logger.warning(f"⚠️ Failed to send reply. Leaving email UNSEEN for retry.")
        else:
            mail.store(msg_id, '+FLAGS', '\\Seen')
            
    except Exception as e:
        logger.error(f"❌ Processing Error: {e}", exc_info=True)

def run_imap_poller():
    logger.info(f"🔌 Connecting to {IMAP_SERVER}:{IMAP_PORT}...")
    while True:
        mail = None
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
            mail.login(EMAIL_ADDR, EMAIL_PASS)
            mail.select("INBOX")
            
            logger.info("🧹 Cleaning Inbox: Marking all existing emails as SEEN...")
            mail.store('1:*', '+FLAGS', '\\Seen')
            logger.info(f"✅ Inbox Cleaned. Polling every {POLL_INTERVAL}s for NEW mail...")
            
            while True:
                res, msgs = mail.search(None, '(UNSEEN)')
                msg_ids = msgs[0].split()
                
                if msg_ids:
                    logger.info(f"🔔 {len(msg_ids)} NEW message(s)!")
                    for msg_id in msg_ids:
                        fetch_and_process_email(mail, msg_id)
                
                time.sleep(POLL_INTERVAL)
                    
        except Exception as e:
            logger.error(f"❌ Connection Error: {e}")
            if mail:
                try: mail.close()
                except: pass
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    print("="*50)
    print("📧 EMAIL DAEMON (Fast 15s Polling)")
    print("="*50)
    try:
        run_imap_poller()
    except KeyboardInterrupt:
        print("\n🛑 Stopped.")
