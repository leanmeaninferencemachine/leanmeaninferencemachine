# app/memory/__init__.py
"""Memory subpackage for LMIM Engine — class-based layers."""

from app.memory.base import MemoryLayer
from app.memory.episodic import EpisodicMemory
from app.memory.conversation_summary import ConversationSummary

# Optional: Factory function for future expansion
# (Currently only supports episodic; global/legacy handled elsewhere)
from typing import Optional

def get_memory_layer(scope: str, user_id: Optional[str] = None, **kwargs) -> MemoryLayer:
    """Factory: return appropriate memory layer instance."""
    if scope == "episodic":
        if not user_id:
            raise ValueError("user_id required for episodic memory")
        return EpisodicMemory(user_id=user_id, **kwargs)
    elif scope == "global":
        # Fallback to legacy function-based memory for now
        # (GlobalMemory class not yet implemented)
        from app.memory_functions import store_memory, recall_memories
        # Return a lightweight adapter if needed, or raise for now
        raise NotImplementedError("GlobalMemory class not yet implemented; use legacy functions")
    else:
        raise ValueError(f"Unknown memory scope: {scope}")

__all__ = [
    "MemoryLayer",
    "EpisodicMemory", 
    "ConversationSummary",
    "get_memory_layer"
]
