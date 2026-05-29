"""
Telegram Agent: Listens for TG events, processes via LMIM Core, and replies.
"""
import logging
import asyncio
from app.events.base import EventType, Event
from app.model_interface import query_model
from app.memory_functions import update_session_memory, get_session_context
from app.config import ENABLE_TOOL_CALLING

logger = logging.getLogger(__name__)

class TelegramAgent:
    def __init__(self):
        self.name = "TelegramAgent"
        logger.info("🤖 Telegram Agent initialized")

    async def handle_incoming_message(self, event: Event):
        """Process incoming Telegram message."""
        payload = event.payload
        user_id = payload.get("user_id")
        user_name = payload.get("user_name")
        text = payload.get("text")
        chat_id = payload.get("chat_id")
        message_id = payload.get("message_id")
        platform = "telegram"

        if not text:
            return

        logger.info(f"📩 Processing TG Message from {user_name}: {text[:50]}...")

        # 1. Get Context (Memory)
        # We use the same memory system as WhatsApp
        context = get_session_context(user_id, top_k=5)
        
        # 2. Construct Prompt
        # Inject platform-specific identity
        system_prefix = f"You are LMIM, assisting a user on **Telegram**. User: {user_name}."
        
        full_prompt = f"{system_prefix}\n\nContext: {context}\n\nUser: {text}"

        # 3. Call Model
        try:
            reply = query_model(
                prompt=full_prompt,
                user_id=user_id,
                conversation_history=None, # Handled by memory context for now
                builder_mode=False
            )

            # 4. Update Memory
            update_session_memory(user_id, text, reply)

            # 5. Emit Reply Event
            if reply:
                logger.info(f"💬 Generated Reply: {reply[:50]}...")
                
                # Emit event for the Daemon to send
                from app.events.base import emit
                emit(EventType.TELEGRAM_REPLY_READY, payload={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": reply,
                    "platform": "telegram",
                    "user_id": user_id
                })
            else:
                logger.warning("Model returned empty reply.")

        except Exception as e:
            logger.error(f"Error processing TG message: {e}", exc_info=True)
            # Emit error reply
            from app.events.base import emit
            emit(EventType.TELEGRAM_REPLY_READY, payload={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "⚠️ Sorry, I encountered an error processing your request.",
                "platform": "telegram"
            })

# Global Instance
_telegram_agent = None

def init_telegram_agent(event_bus):
    global _telegram_agent
    _telegram_agent = TelegramAgent()
    
    if event_bus:
        # Subscribe to Incoming Messages
        event_bus.subscribe(EventType.TELEGRAM_MESSAGE_INCOMING, _telegram_agent.handle_incoming_message, priority=5)
        logger.debug("✅ Telegram Agent handlers registered")
    
    return _telegram_agent

def get_telegram_agent():
    return _telegram_agent
