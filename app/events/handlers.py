# app/events/handlers.py
"""
Event Handlers: Bridge between Event Bus and existing LMIM logic.
- Registers handlers for event types
- Delegates to existing memory/tools via wrappers
- Error isolation + structured logging
"""

from typing import Callable, Dict, Any, Optional
import sys
import os
import json
import logging
from pathlib import Path

# Dynamic path resolution (no hardcoding)
BASE_DIR = Path(__file__).resolve().parents[2]  # app/events/ → app/ → project_root
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class EventHandler:
    """
    Registry for event → function mappings.
    Handlers execute synchronously; wrap async logic in threads if needed later.
    """
    
    def __init__(self):
        self.handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
    
    def register(self, event_type: str, handler: Callable[[Dict[str, Any]], Any]):
        """Register a handler function for a specific event type."""
        self.handlers[event_type] = handler
        logger.info(f"[HANDLER] Registered: '{event_type}' → {handler.__name__}")
    
    def unregister(self, event_type: str) -> bool:
        """Remove a handler registration."""
        if event_type in self.handlers:
            del self.handlers[event_type]
            logger.info(f"[HANDLER] Unregistered: '{event_type}'")
            return True
        return False
    
    def trigger(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the handler for an event type.
        
        Returns:
            Dict with 'success', 'data' or 'error' keys
        """
        handler = self.handlers.get(event_type)
        if not handler:
            logger.warning(f"[HANDLER] No handler registered for '{event_type}'")
            return {"success": False, "error": f"No handler for event type: {event_type}"}
        
        logger.debug(f"[HANDLER] Executing: '{event_type}' with payload keys: {list(payload.keys())}")
        
        try:
            result = handler(payload)
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"[HANDLER] Error in {handler.__name__}: {e}", exc_info=True)
            return {"success": False, "error": str(e), "type": type(e).__name__}


# ─────────────────────────────────────────────────────────────
# GLOBAL HANDLER INSTANCE + REGISTRATIONS
# ─────────────────────────────────────────────────────────────

handler_instance = EventHandler()


def handle_store_memory(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for STORE_MEMORY events.
    Delegates to MemoryToolWrapper for actual persistence.
    """
    from app.tools.memory_tools import MemoryToolWrapper
    
    wrapper = MemoryToolWrapper()
    content = payload.get("content")
    importance = payload.get("importance", 1)
    
    if not content:
        raise ValueError("STORE_MEMORY requires 'content' in payload")
    
    return wrapper.store(content=content, importance=importance)


def handle_recall_memory(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Handler for RECALL_MEMORY events."""
    from app.tools.memory_tools import MemoryToolWrapper
    
    wrapper = MemoryToolWrapper()
    query = payload.get("query")
    top_k = payload.get("top_k", 3)
    
    if not query:
        raise ValueError("RECALL_MEMORY requires 'query' in payload")
    
    return wrapper.recall(query=query, top_k=top_k)


# Register handlers at module load
handler_instance.register("STORE_MEMORY", handle_store_memory)
handler_instance.register("RECALL_MEMORY", handle_recall_memory)

logger.info("[HANDLER] Module initialized with %d registered handlers", len(handler_instance.handlers))
