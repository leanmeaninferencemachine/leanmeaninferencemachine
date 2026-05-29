"""
app/tools/whatsapp_tool_electron.py

Replaces the Playwright-based WhatsApp daemon with direct HTTP calls
to the Electron IPC server (whatsapp-window.js on port 5002).

Drop-in replacement for wherever the old whatsapp_daemon was called:
  - SendWhatsAppTool.run()
  - The /webhooks/whatsapp/incoming route stays unchanged
  - The daemon-control / daemon-states API endpoints return static state

Usage in Flask code:
    from app.tools.whatsapp_tool_electron import send_whatsapp, get_whatsapp_status
"""

import os
import json
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# Port where whatsapp-window.js IPC server listens
_WA_IPC_PORT = int(os.getenv('LMIM_WA_IPC_PORT', '5002'))
_WA_BASE     = f'http://127.0.0.1:{_WA_IPC_PORT}'
_TIMEOUT     = 35   # seconds — long enough for WA navigation + send


def send_whatsapp(phone: str, message: str) -> dict:
    """
    Send a WhatsApp message via the Electron IPC server.

    Returns:
        { 'ok': True }  on success
        { 'ok': False, 'error': '...' }  on failure
    """
    clean_phone = ''.join(c for c in str(phone) if c.isdigit())
    if not clean_phone:
        return {'ok': False, 'error': f'Invalid phone number: {phone}'}

    try:
        resp = requests.post(
            f'{_WA_BASE}/send',
            json={'phone': clean_phone, 'text': str(message)},
            timeout=_TIMEOUT,
        )
        data = resp.json()
        if resp.status_code == 200 and data.get('ok'):
            logger.info(f'✅ WhatsApp sent to {clean_phone}')
            return {'ok': True}
        else:
            err = data.get('error', f'HTTP {resp.status_code}')
            logger.warning(f'⚠️  WhatsApp send failed for {clean_phone}: {err}')
            return {'ok': False, 'error': err}
    except requests.exceptions.ConnectionError:
        msg = (
            'WhatsApp IPC server not reachable (port 5002). '
            'Is the Electron app running?'
        )
        logger.error(f'❌ {msg}')
        return {'ok': False, 'error': msg}
    except Exception as e:
        logger.error(f'❌ WhatsApp send exception: {e}')
        return {'ok': False, 'error': str(e)}


def get_whatsapp_status() -> dict:
    """
    Returns the current WhatsApp connection status from the Electron daemon.

    Returns:
        {
            'loggedIn':  bool,
            'hasQR':     bool,
            'lastCheck': int (epoch ms),
            'window':    'hidden' | 'visible' | 'closed',
        }
    """
    try:
        resp = requests.get(f'{_WA_BASE}/status', timeout=3)
        return resp.json()
    except Exception:
        return {'loggedIn': False, 'hasQR': False, 'lastCheck': 0, 'window': 'unknown'}


def show_whatsapp_window() -> dict:
    """Ask Electron to show the WhatsApp window (e.g. for QR scan)."""
    try:
        resp = requests.post(f'{_WA_BASE}/show', timeout=3)
        return resp.json()
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def hide_whatsapp_window() -> dict:
    """Hide the WhatsApp window."""
    try:
        resp = requests.post(f'{_WA_BASE}/hide', timeout=3)
        return resp.json()
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ---------------------------------------------------------------------------
# Compatibility shim: matches the old SendWhatsAppTool interface so existing
# Flask routes that called the old tool class continue to work unchanged.
# ---------------------------------------------------------------------------
class SendWhatsAppTool:
    """
    Drop-in replacement for the Playwright-based SendWhatsAppTool.
    Forwards to the Electron IPC server instead of a subprocess daemon.
    """

    def __init__(self):
        data_dir = os.getenv('LMIM_DATA_DIR', str(
            __import__('pathlib').Path.home() / '.lmim_os'
        ))
        queue_path = __import__('pathlib').Path(data_dir) / 'whatsapp_outbound_queue.json'
        logger.info(f'📍 SendWhatsAppTool (Electron): IPC port {_WA_IPC_PORT}')
        logger.info(f'📍 Queue path (legacy, unused): {queue_path}')

    def run(self, phone: str, message: str) -> str:
        result = send_whatsapp(phone, message)
        if result['ok']:
            return f'✅ Message sent to {phone}'
        return f'❌ Failed to send to {phone}: {result.get("error", "unknown error")}'

    # Legacy method used by some Flask routes
    def queue_message(self, phone: str, message: str) -> dict:
        return send_whatsapp(phone, message)
