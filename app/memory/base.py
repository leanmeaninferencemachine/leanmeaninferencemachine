# app/memory/base.py
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class MemoryLayer(ABC):
    """Abstract base class for all memory types."""
    
    def __init__(self, user_id: Optional[str] = None, max_entries: int = 50):
        self.user_id = user_id
        self.max_entries = max_entries
        self.created_at = datetime.now()
    
    @abstractmethod
    def store(self, key: str, value: str, meta: Optional[Dict] = None) -> bool:
        """Store a memory entry. Returns success bool."""
        pass
    
    @abstractmethod
    def recall(self, query: str, top_k: int = 3) -> List[Dict]:
        """Retrieve matching memories."""
        pass
    
    @abstractmethod
    def list_keys(self, tag: Optional[str] = None) -> List[str]:
        """List stored keys, optionally filtered by tag."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a memory entry by key."""
        pass
    
    def _apply_ttl(self, entries: List[Dict], ttl_hours: Optional[int] = None) -> List[Dict]:
        """Filter entries by time-to-live (optional)."""
        if not ttl_hours:
            return entries
        cutoff = datetime.now() - timedelta(hours=ttl_hours)
        return [e for e in entries if e.get("metadata", {}).get("created_at", 0) > cutoff.timestamp()]
    
    def _normalize_tags(self, meta: Optional[Dict]) -> List[str]:
        """Normalize tags to lowercase list."""
        if not meta or "tags" not in meta:
            return []
        tags = meta["tags"]
        if isinstance(tags, str):
            return [t.strip().lower() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            return [str(t).strip().lower() for t in tags if str(t).strip()]
        return []
