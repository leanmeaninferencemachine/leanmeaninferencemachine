#!/usr/bin/env python3

import json
import logging
import sqlite3
import re
import time
import os
import sys
from pathlib import Path
from typing import Dict, Any, List
from app.model_interface import query_model
from app.config import TOOL_CALL_MARKER_START, TOOL_CALL_MARKER_END
from app.events.base import event_bus, EventType, emit
from app.memory_functions import get_recent_chat_history, log_whatsapp_chat_turn
from app.tools.contacts_tools import find_contact_by_name, find_contact_by_phone

logger = logging.getLogger(__name__)


# =============================================================================
# 📞 PHONE NUMBER NORMALIZATION (for incoming messages)
# =============================================================================
def normalize_mexican_phone(text: str) -> str:
    """
    Convert Mexican phone formats to international standard (without the 1).
    Converts "+52 1 664 529 7303" to "+52 664 529 7303"
    This prevents the model from misinterpreting the '1' as a prefix.
    """
    if not text:
        return text
    # Pattern: +52 1 664 529 7303 or +52 1 6645297303 or 52 1 664 529 7303
    pattern = r'(\+?52)\s*1\s*(\d{3})\s*(\d{3})\s*(\d{4})'
    replacement = r'\1 \2 \3 \4'
    return re.sub(pattern, replacement, text)


# =============================================================================
# Path helpers
# =============================================================================
def get_writable_data_dir():
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent.parent / 'data'


DATA_DIR     = get_writable_data_dir()
MEMORIES_DIR = DATA_DIR / 'memories'
DB_PATH      = DATA_DIR / 'lmim.db'
PROFILES_DIR = DATA_DIR / 'profiles'
CLIENTS_DIR  = DATA_DIR / 'clients'

if not DB_PATH.exists():
    DB_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'lmim.db'


# =============================================================================
# WhatsAppAgent
# =============================================================================
class WhatsAppAgent:
    def __init__(self):
        try:
            self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            logger.debug(f'📱 Connected to SQLite DB at {DB_PATH}')
        except Exception as e:
            logger.warning(f'⚠️ Could not connect to SQLite DB at {DB_PATH}: {e}')
            self.conn = None

        logger.info(f'📱 WhatsApp Agent Initialized (Data Dir: {DATA_DIR})')

    # ── Contact resolution helper ───────────────────────────────────────────────
    def _resolve_contact_phone(self, user_id: str, identifier: str):
        """Resolve a name or phone to a phone number using contacts list."""
        import re
        
        # If it's already a phone number, return cleaned version
        if re.match(r'^[\+\d\s\-]{8,}$', identifier.strip()):
            return re.sub(r'[^\d+]', '', identifier)
        
        # Try to find by name
        contact = find_contact_by_name(user_id, identifier)
        if contact:
            return contact.get('phone')
        
        return None


    # ── Event bus entry point ─────────────────────────────────────────────────
    def handle_message(self, event_payload: dict) -> str:
        phone = event_payload.get('phone')
        text  = event_payload.get('text')
        if not phone or not text:
            return '⚠️ Invalid payload.'
        return self.process_message_sync(phone, text)

    # ── Profile loader ────────────────────────────────────────────────────────
    def _get_profile_for_phone(self, phone: str) -> Dict[str, Any]:
        user_id  = f'wa_{phone}'
        user_dir = MEMORIES_DIR / 'users' / user_id

        default_config = {
            'agent_name':  'LMIM Assistant',
            'tone':        'witty, sarcastic, direct',
            'caller_name': phone,
            'profile_id':  user_id,
            'notes':       'New Contact (No profile found)',
            'signature':   '- Asistente de Andrés',
        }

        if not user_dir.exists():
            logger.debug(f'⚠️ No JSON profile found for {phone}. Using defaults.')
            return default_config

        config = default_config.copy()
        state_file   = user_dir / 'state.json'
        memories_file = user_dir / 'memories.json'

        if state_file.exists():
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                if state.get('name'):
                    config['caller_name'] = state['name']
                if state.get('preferences'):
                    config['notes'] = str(state.get('preferences'))
                if state.get('role'):
                    config['user_role'] = state.get('role')
                logger.debug(f"✅ Loaded state for {user_id}: {config['caller_name']}")
            except Exception as e:
                logger.warning(f'⚠️ Could not read state for {user_id}: {e}')

        if memories_file.exists():
            try:
                with open(memories_file, 'r', encoding='utf-8') as f:
                    memories = json.load(f)
                config['memory_count'] = len(memories) if isinstance(memories, list) else 0
            except Exception as e:
                logger.warning(f'⚠️ Could not read memories for {user_id}: {e}')

        return config

    # ── System prompt builder ─────────────────────────────────────────────────
    def _build_system_prompt(self, config: Dict[str, Any]) -> str:
        caller_name = config.get('caller_name', 'Unknown')
        signature   = config.get('signature', '- Asistente de Andrés')

        identity_block = f"""
### ROLE DEFINITION
You are {config.get('agent_name')}, the AI assistant for Andrés Israel Santos.
Caller: {caller_name}
Language: {config.get('language', 'es')}
Tone: {config.get('tone')}

### CRITICAL INSTRUCTIONS
1. You are the ASSISTANT. The user is speaking to YOU.
2. NEVER say "I don't need" or speak as if you are the user.
3. If the user says "Para agendar...", they want YOU to help THEM schedule.
4. Be concise, warm, and direct.
5. Sign off with: "{signature}"
""".strip()

        tool_block = f"""
### 🛠️ AVAILABLE TOOLS (CRITICAL)
If the user asks to "search", "check online", "find news", or "look up":
1. **STOP** thinking.
2. **OUTPUT** a tool call marker immediately.
3. **WAIT** for the result.

**Format:**
{TOOL_CALL_MARKER_START}{{"name": "web_search", "parameters": {{"query": "user's topic"}}}}{TOOL_CALL_MARKER_END}

**Available Tools:**
- `web_search`: Search DuckDuckGo (Smart Filter: 10→3 results).
- `store_memory`: Save a fact.
- `recall_memory`: Remember a fact.
- `send_whatsapp`: Send a WhatsApp message to a phone number.

**RULE:** If the user asks for current info, YOU MUST use `web_search`.
""".strip()

        return f'{identity_block}\n\n{tool_block}'

    # ── Main message handler ──────────────────────────────────────────────────
    def process_message_sync(self, phone: str, text: str,
                             system_prompt_override: str = None) -> str:
        # 🔥 Normalize phone numbers in incoming messages
        text = normalize_mexican_phone(text)
        
        user_id = f'wa_{phone}'

        # 1. Load profile
        config = self._get_profile_for_phone(phone)

        # 2. Load history
        recent_history = get_recent_chat_history(user_id, limit=5)

        # 3. Build context block
        if recent_history:
            lines = []
            for msg in recent_history:
                role    = 'User' if msg['role'] == 'user' else 'Assistant'
                content = msg['content'].strip()
                lines.append(f'{role}: {content}')
            joined_lines = '\n'.join(lines)
            context_block = f'\n### RECENT CONVERSATION HISTORY\n{joined_lines}\n'.strip()
        else:
            context_block = '### NO PREVIOUS HISTORY'

        # 4. Construct final prompt
        if system_prompt_override:
            base_prompt = system_prompt_override
            logger.debug('✅ Using System Prompt Override from Router')
        else:
            base_prompt = self._build_system_prompt(config)
            logger.debug('✅ Using internal system prompt builder.')

        full_prompt = f"""
{base_prompt}

{context_block}

### CURRENT INPUT
User: {text}

Your response:
""".strip()

        # 5. Search keyword check → status update
        search_keywords = ['busca', 'buscar', 'search', 'google',
                           'online', 'internet', 'noticias']
        if any(kw in text.lower() for kw in search_keywords):
            logger.info('⏳ Search keyword detected. Sending status update...')
            try:
                emit(EventType.WHATSAPP_STATUS_UPDATE,
                     payload={'phone': phone,
                               'text': '⏳ Un momento, buscando en internet...'})
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f'⚠️ Failed to emit status update: {e}')

        logger.debug(f'🚀 Sending to Model (Len: {len(full_prompt)})')

        # 6. Query model
        try:
            response = query_model(
                prompt=full_prompt,
                user_id=user_id,
                builder_mode=False,
            )

            # Strip common prefixes the model sometimes adds
            for prefix in ('User:', 'Assistant:', 'AI:'):
                if response.startswith(prefix):
                    response = response[len(prefix):].strip()

            # Append signature if missing
            signature = config.get('signature', '')
            if (signature and
                    '[TOOL_CALL]' not in response and
                    not response.endswith(signature)):
                response += f'\n{signature}'

            # 7. Save turn
            log_whatsapp_chat_turn(user_id, text, response, max_turns=20)
            return response

        except Exception as e:
            logger.error(f'❌ Model Error: {e}', exc_info=True)
            return 'Error processing message.'

    async def handle_incoming_message(self, event_payload: Dict[str, Any]):
        phone = event_payload.get('phone')
        text  = event_payload.get('text')
        reply = self.process_message_sync(phone, text)
        emit(EventType.WHATSAPP_MESSAGE_OUTGOING,
             payload={'phone': phone, 'text': reply})


# =============================================================================
# Registration
# =============================================================================
def register_whatsapp_agent():
    agent = WhatsAppAgent()
    event_bus.subscribe(EventType.WHATSAPP_MESSAGE_INCOMING,
                        agent.handle_message, priority=5)
    logger.info('✅ WhatsApp Agent Registered (Transcript + Tools + Smart Search).')
    return agent


if __name__ == '__main__':
    register_whatsapp_agent()
