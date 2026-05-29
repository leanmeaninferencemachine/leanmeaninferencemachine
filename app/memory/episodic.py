# app/memory/episodic.py — TOP OF FILE
import json
import time
from pathlib import Path
from typing import Optional, List, Dict
# ← Use absolute import from app.memory package
from app.memory.base import MemoryLayer
from app.config import MEMORY_DIR, MEMORY_RETRIEVAL_TOP_K, PERSISTENT_MEMORY_ENABLED
import logging

logger = logging.getLogger(__name__)

class EpisodicMemory(MemoryLayer):
    """User-specific facts with tags: preferences, goals, facts."""
    
    VALID_TAGS = {"preferences", "goals", "facts", "progress", "feedback"}
    
    def __init__(self, user_id: str, max_entries: int = 50, tag: Optional[str] = None):
        super().__init__(user_id, max_entries)
        if tag and tag not in self.VALID_TAGS:
            raise ValueError(f"Invalid tag: {tag}. Must be one of {self.VALID_TAGS}")
        self.tag = tag
        self.base_path = Path(MEMORY_DIR) / "episodic" / user_id
    
    def _get_file_path(self, tag: Optional[str] = None) -> Path:
        """Get path for tag-specific file, or combined if no tag."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        if tag:
            return self.base_path / f"{tag}.json"
        return self.base_path / "all.json"
    
    def _load_entries(self, tag: Optional[str] = None) -> List[Dict]:
        """Load entries from file."""
        if not PERSISTENT_MEMORY_ENABLED:
            return []
        path = self._get_file_path(tag or self.tag)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("entries", [])
        except (json.JSONDecodeError, IOError):
            logger.warning(f"Failed to load {path}")
            return []
    
    def _save_entries(self, entries: List[Dict], tag: Optional[str] = None):
        """Save entries to file."""
        if not PERSISTENT_MEMORY_ENABLED:
            return
        path = self._get_file_path(tag or self.tag)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"entries": entries, "last_updated": time.time()}, f, indent=2, ensure_ascii=False)
    
    def _normalize_tags(self, meta: Optional[Dict]) -> List[str]:
        """Normalize tags to lowercase list (reusable helper)."""
        if not meta or "tags" not in meta:
            return []
        tags = meta["tags"]
        if isinstance(tags, str):
            return [t.strip().lower() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            return [str(t).strip().lower() for t in tags if str(t).strip()]
        return []
    
    def store(self, key: str, value: str, meta: Optional[Dict] = None) -> bool:
        """Store an episodic memory with tag support."""
        if not PERSISTENT_MEMORY_ENABLED:
            return False
        
        tags = self._normalize_tags(meta)
        entry_tag = self.tag or (tags[0] if tags else "facts")
        if entry_tag not in self.VALID_TAGS:
            entry_tag = "facts"
        
        entries = self._load_entries(entry_tag)
        entries = [e for e in entries if e.get("key") != key]
        
        entries.append({
            "key": key,
            "value": value,
            "metadata": {
                **(meta or {}),
                "tags": tags,
                "tag": entry_tag,
                "importance": meta.get("importance", 0.5),
                "created_at": time.time()
            }
        })
        
        if len(entries) > self.max_entries:
            entries = entries[-self.max_entries:]
        
        self._save_entries(entries, entry_tag)
        logger.info(f"EpisodicMemory.store: user={self.user_id}, tag={entry_tag}, key={key}")
        return True
    
    def recall(self, query: str, top_k: int = 3, tag: Optional[str] = None) -> List[Dict]:
        """Retrieve episodic memories with keyword + tag filtering."""
        if not PERSISTENT_MEMORY_ENABLED:
            return []
        
        if tag:
            entries = self._load_entries(tag)
        elif self.tag:
            entries = self._load_entries(self.tag)
        else:
            entries = []
            for t in self.VALID_TAGS:
                entries.extend(self._load_entries(t))
        
        if not entries:
            return []
        
        return self._score_entries(entries, query, top_k)
    
    def _score_entries(self, entries: List[Dict], query: str, top_k: int) -> List[Dict]:
        """Score entries by relevance with importance + recency boosting."""
        query_lower = query.lower().strip()
        query_words = set(query_lower.split())
        scored = []
        
        for e in entries:
            key = e.get("key", "").lower()
            value = e.get("value", "").lower()
            tags = e.get("metadata", {}).get("tags", [])
            
            searchable = f"{key} {value} {' '.join(tags)}"
            score = 0
            
            # Split underscored keys for better matching
            text_words = set(searchable.split())
            for word in list(text_words):
                if '_' in word and len(word) > 3:
                    for part in word.split('_'):
                        if len(part) > 2:
                            text_words.add(part.lower())
            
            # 1. Exact word match
            exact_matches = query_words & text_words
            if exact_matches:
                score += len(exact_matches) * 2
            
            # 2. Substring + partial match
            for qw in query_words:
                if len(qw) <= 2:
                    continue
                if qw in key or qw in value or qw in tags:
                    score += 1
                elif any((qw in tw or tw in qw) and abs(len(qw) - len(tw)) <= 2 
                        for tw in text_words if len(tw) > 2):
                    score += 0.5
            
            # Only proceed if we have a match
            if score > 0:
                recency = e.get("metadata", {}).get("created_at", 0) / (time.time() + 1)
                importance = e.get("metadata", {}).get("importance", 0.5)
                importance_weight = 0.3
                final_score = (score + 0.05 * recency) * (1 + importance * importance_weight)
                scored.append((final_score, e))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]
    
    def list_keys(self, tag: Optional[str] = None) -> List[str]:
        """List stored keys, optionally filtered by tag."""
        entries = self._load_entries(tag or self.tag)
        return [e.get("key") for e in entries if e.get("key")]
    
    def delete(self, key: str) -> bool:
        """Delete a memory entry by key."""
        tag = self.tag or "facts"
        entries = self._load_entries(tag)
        original_len = len(entries)
        entries = [e for e in entries if e.get("key") != key]
        
        if len(entries) < original_len:
            self._save_entries(entries, tag)
            logger.info(f"EpisodicMemory.delete: user={self.user_id}, key={key}")
            return True
        return False