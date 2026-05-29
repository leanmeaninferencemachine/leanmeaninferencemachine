"""Communication Tools: WhatsApp, Telegram & Email."""
import os
import requests
import logging
from app.tools.contacts_tools import find_contact_by_name
import json
import time
import sys
from pathlib import Path
from typing import Dict, Any
from app.tools.base_tool import BaseTool

logger = logging.getLogger(__name__)

# ── WhatsApp IPC port (set by Electron's main.js via LMIM_WA_IPC_PORT) ────────
_WA_IPC_PORT = int(os.getenv('LMIM_WA_IPC_PORT', '5002'))
_WA_IPC_BASE = f'http://127.0.0.1:{_WA_IPC_PORT}'
# 90s: covers navigation (25s) + typing + send button + verification (10s)
# The Electron IPC server only responds after the full send completes
_WA_SEND_TIMEOUT = 90



class SendWhatsAppTool(BaseTool):
    name = "send_whatsapp"
    description = "Send a WhatsApp message via the Electron WhatsApp window."

    def __init__(self):
        super().__init__()
        # Keep queue path for legacy status endpoint compatibility
        data_dir = Path(os.getenv('LMIM_DATA_DIR', '')) or (
            Path.home() / '.lmim_os'
            if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parent.parent.parent / 'data'
        )
        self.queue_path = data_dir / 'whatsapp_outbound_queue.json'
        logger.info(f'📍 SendWhatsAppTool: IPC port {_WA_IPC_PORT}')
        logger.info(f'📍 SendWhatsAppTool: Queue path initialized to: {self.queue_path}')

    def execute(self, params: Dict[str, Any]) -> str:
        phone   = params.get('phone') or params.get('to') or params.get('number', '')
        
        # Resolve contact name to phone number
        original_phone = phone
        if phone and not phone.startswith('+') and not phone.isdigit():
            try:
                from app.tools.contacts_tools import find_contact_by_name
                resolved = find_contact_by_name('default', phone)
                if resolved:
                    phone = resolved.get('phone')
                    logger.info(f"📱 Resolved contact '{original_phone}' to '{phone}'")
            except Exception as e:
                logger.debug(f"Contact resolution failed: {e}")
        message = params.get('message') or params.get('text') or params.get('body', '')

        if not phone or not message:
            return "❌ ERROR: Missing 'phone' or 'message'."

        # Clean phone — digits only (keep leading +)
        phone_str = str(phone).strip()
        digits = ''.join(c for c in phone_str if c.isdigit())
        clean_phone = ('+' + digits) if phone_str.startswith('+') else digits
        if not clean_phone:
            return f"❌ ERROR: Invalid phone number: {phone}"

        logger.info(f'📱 Sending WhatsApp to {clean_phone} via Electron IPC...')

        try:
            resp = requests.post(
                f'{_WA_IPC_BASE}/send',
                json={'phone': clean_phone, 'text': str(message)},
                timeout=_WA_SEND_TIMEOUT,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get('ok'):
                logger.info(f'✅ WhatsApp sent to {clean_phone}')
                return (
                    f'✅ SUCCESS: WhatsApp message sent to **{phone}**.\n'
                    f"Message: '{message[:80]}{'...' if len(message) > 80 else ''}'"
                )
            err = data.get('error', f'HTTP {resp.status_code}')
            logger.warning(f'⚠️  WhatsApp send failed for {clean_phone}: {err}')
            return f'❌ ERROR: Failed to send to {phone}: {err}'

        except requests.exceptions.ConnectionError:
            # Electron daemon not running — this happens in dev/test without Electron
            msg = (
                f'⚠️  WhatsApp IPC server not reachable (port {_WA_IPC_PORT}). '
                'Message queued for when Electron is running.'
            )
            logger.warning(msg)
            self._queue_fallback(clean_phone, message)
            return msg

        except Exception as e:
            logger.error(f'❌ WhatsApp send exception: {e}', exc_info=True)
            return f'❌ ERROR: {str(e)}'

    def _queue_fallback(self, phone: str, message: str):
        """
        Write to the legacy queue file as a fallback when Electron IPC is
        unreachable (e.g. dev mode without Electron running).
        The queue file is also read by the /api/internal/wa-status endpoint.
        """
        try:
            queue = []
            if self.queue_path.exists():
                try:
                    with open(self.queue_path, 'r', encoding='utf-8') as f:
                        queue = json.load(f)
                except json.JSONDecodeError:
                    queue = []
            queue.append({
                'phone':     phone,
                'message':   message,
                'timestamp': time.time(),
                'status':    'pending',
            })
            self.queue_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.queue_path, 'w', encoding='utf-8') as f:
                json.dump(queue, f, indent=2)
            logger.info(f'📝 Fallback: queued message for {phone} in {self.queue_path}')
        except Exception as e:
            logger.error(f'❌ Fallback queue write failed: {e}')

    # Legacy compatibility method
    def queue_message(self, phone: str, message: str) -> dict:
        result = self.execute({'phone': phone, 'message': message})
        ok = '✅' in result
        return {'ok': ok, 'message': result}


# =============================================================================
# SendTelegramTool  (unchanged from original)
# =============================================================================
class SendTelegramTool:
    def execute(self, params: dict):
        chat_id = (params.get('chat_id') or params.get('username') or
                   params.get('user') or params.get('chat_id_str'))
        message = params.get('message') or params.get('text') or params.get('body')

        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            return '❌ Error: TELEGRAM_BOT_TOKEN not configured in .env'
        if not chat_id:
            return '❌ Error: Missing recipient (chat_id or username).'
        if not message:
            return '❌ Error: Missing message content.'

        if isinstance(chat_id, str) and chat_id.startswith('@'):
            logger.info(f'Sending to username: {chat_id}')
        elif isinstance(chat_id, str) and chat_id.isdigit():
            chat_id = int(chat_id)

        try:
            url = f'https://api.telegram.org/bot{token}/sendMessage'
            payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
            logger.info(f'📱 Sending Telegram to {chat_id}...')
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            result_data = resp.json()
            if result_data.get('ok'):
                return f'✅ SUCCESS: Telegram message sent to **{chat_id}**.'
            err = result_data.get('description', 'Unknown error')
            if 'chat not found' in err.lower():
                return (f"⚠️ Error: Bot cannot find user '{chat_id}'. "
                        'The user must start a chat with the bot first.')
            return f'❌ Failed: {err}'
        except requests.exceptions.RequestException as e:
            logger.error(f'Network error: {e}')
            return f'❌ Network error sending Telegram: {str(e)}'
        except Exception as e:
            logger.error(f'Unexpected error: {e}')
            return f'❌ Error: {str(e)}'



class SendEmailTool(BaseTool):
    name = 'send_email'
    description = 'Send an email via SMTP.'

    def execute(self, params: Dict[str, Any]) -> str:
        to_addr = params.get('to', '')
        subject = params.get('subject', '')
        body    = params.get('body', '')

        if not to_addr or not subject:
            return "❌ ERROR: Missing 'to' or 'subject'."

        smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port   = int(os.getenv('SMTP_PORT', '587'))
        smtp_user   = os.getenv('SMTP_USER', '')
        smtp_pass   = os.getenv('SMTP_PASS', '')

        if not smtp_user or not smtp_pass:
            return (
                f'⚠️ EMAIL DRAFTED (Not Sent): SMTP credentials missing in .env.\n\n'
                f'To: {to_addr}\nSubject: {subject}\nBody: {body[:100]}...'
            )

        logger.info(f'📧 Sending Email to {to_addr}: {subject}')
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart()
            msg['From']    = smtp_user
            msg['To']      = to_addr
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            server.quit()
            return f'✅ EMAIL SENT: Successfully delivered to {to_addr}.'
        except Exception as e:
            return f'❌ EMAIL FAILED: SMTP Error - {str(e)}'
