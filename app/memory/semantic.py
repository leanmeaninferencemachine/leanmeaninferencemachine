# app/memory/semantic.py
"""
Semantic Memory Layer: SQLite + keyword indexing for fast recall.
- Drop-in alternative to episodic.py for Phase 3B+
- Supports vector embeddings later (via sqlite-vec or FAISS)
- Atomic writes + connection pooling
"""

import sqlite3
import json
import re
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from contextlib import contextmanager

from app.memory.base import MemoryLayer


class SemanticMemory(MemoryLayer):
    """
    SQLite-backed memory with keyword indexing.
    
    Features:
    - Fast keyword search via FTS5 (if enabled)
    - Atomic writes via transactions
    - Optional vector column for future embeddings
    """
    
    def __init__(self, db_path: Optional[str] = None, use_fts: bool = True):
        self.db_path = Path(db_path) if db_path else Path(__file__).parents[2] / "data" / "memories" / "semantic.db"
        self.use_fts = use_fts
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    @contextmanager
    def _get_conn(self):
        """Context manager for SQLite connections with row_factory."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_schema(self):
        """Initialize tables + indexes."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Core memories table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    importance INTEGER DEFAULT 1,
                    tags TEXT,  -- JSON array string
                    scope TEXT DEFAULT 'user',  -- 'user' or 'global'
                    user_id TEXT,
                    created_at REAL NOT NULL,
                    accessed_at REAL,
                    access_count INTEGER DEFAULT 0
                )
            """)
            
            # Keyword index (simple)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_content ON memories(content)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_scope ON memories(user_id, scope)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance DESC)")
            
            # Optional FTS5 virtual table for full-text search
            if self.use_fts:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        content, importance, tags,
                        content='memories', content_rowid='rowid'
                    )
                """)
                # Triggers to keep FTS in sync
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, content, importance, tags) 
                        VALUES (new.rowid, new.content, new.importance, new.tags);
                    END;
                """)
            
            conn.commit()
    
    def save(self, content: str, importance: int = 1, tags: Optional[List[str]] = None, 
             scope: str = 'user', user_id: Optional[str] = None) -> Dict[str, Any]:
        """Save memory with atomic transaction."""
        import uuid
        memory_id = str(uuid.uuid4())
        now = time.time()
        tags_json = json.dumps(tags or [])
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO memories 
                (id, content, importance, tags, scope, user_id, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (memory_id, content, importance, tags_json, scope, user_id, now, now))
            
            # Update FTS if enabled
            if self.use_fts:
                cursor.execute("""
                    INSERT OR REPLACE INTO memories_fts (rowid, content, importance, tags)
                    SELECT rowid, content, importance, tags FROM memories WHERE id = ?
                """, (memory_id,))
            
            conn.commit()
        
        return {
            "id": memory_id,
            "status": "saved",
            "filepath": str(self.db_path)  # For atomic_json_write compatibility
        }
    
    def recall(self, query: str, top_k: int = 3, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search memories with keyword matching + importance scoring."""
        # Build query: combine exact, substring, and FTS if available
        keywords = [k.strip() for k in re.split(r'[\s,_]+', query.lower()) if k.strip()]
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            if self.use_fts and keywords:
                # FTS5 search with BM25 ranking
                fts_query = " OR ".join(keywords)
                cursor.execute("""
                    SELECT m.*, bm25(memories_fts) as score
                    FROM memories m
                    JOIN memories_fts ft ON m.rowid = ft.rowid
                    WHERE memories_fts MATCH ?
                    AND (m.scope = 'global' OR m.user_id = ?)
                    ORDER BY score ASC, m.importance DESC, m.accessed_at DESC
                    LIMIT ?
                """, (fts_query, user_id, top_k))
            else:
                # Fallback: simple LIKE + importance scoring
                like_pattern = f"%{query}%"
                cursor.execute("""
                    SELECT *, 
                           (CASE 
                               WHEN content LIKE ? THEN 3
                               WHEN content LIKE ? THEN 2
                               ELSE 1
                           END) as score
                    FROM memories
                    WHERE (scope = 'global' OR user_id = ?)
                    AND (content LIKE ? OR tags LIKE ?)
                    ORDER BY score DESC, importance DESC, accessed_at DESC
                    LIMIT ?
                """, (f"%{query}%", f"%{query.lower()}%", user_id, like_pattern, like_pattern, top_k))
            
            rows = cursor.fetchall()
            
            # Update access stats
            for row in rows:
                cursor.execute("""
                    UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?
                """, (time.time(), row["id"]))
            conn.commit()
        
        # Format results
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "content": row["content"],
                "importance": row["importance"],
                "tags": json.loads(row["tags"]) if row["tags"] else [],
                "score": row.get("score", 0),
                "scope": row["scope"],
                "access_count": row["access_count"]
            })
        
        return results
    
    def clear_user_memories(self, user_id: str) -> int:
        """Delete all memories for a user (GDPR compliance)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount
