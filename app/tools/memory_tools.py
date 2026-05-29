# app/tools/memory_tools.py
import json
import os
import tempfile
import shutil
import sys
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# 🔥 CRITICAL: Dynamic Path Resolution
def get_writable_memories_dir() -> Path:
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        mem_dir = Path(env_path) / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        return mem_dir
    # Fallback
    if getattr(sys, 'frozen', False):
        mem_dir = Path.home() / ".lmim_os" / "memories"
    else:
        mem_dir = Path(__file__).resolve().parent.parent.parent / "data" / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir

MEMORIES_DIR = get_writable_memories_dir()

def atomic_json_write(filepath: Path, data: Dict[str, Any]) -> bool:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        shutil.move(temp_path, filepath)
        return True
    except Exception as e:
        if os.path.exists(temp_path): os.unlink(temp_path)
        raise e

class MemoryToolWrapper:
    USE_SQLITE = False
    SQLITE_PATH = MEMORIES_DIR / "memory_index.db"
    
    def __init__(self):
        # Lazy import to avoid circular deps if episodic.py isn't ready
        try:
            from app.memory.episodic import EpisodicMemory
            self.mem = EpisodicMemory()
            # Override episodic save path if it uses hardcoded paths
            if hasattr(self.mem, 'storage_path'):
                self.mem.storage_path = MEMORIES_DIR / "episodic.json"
        except ImportError:
            logger.warning("⚠️ EpisodicMemory not found. Using dummy storage.")
            self.mem = None
    
    def store(self, content: str, importance: int = 1, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        if not self.mem:
            # Dummy store for safety
            return {"result": content[:50], "status": "success", "metadata": {"note": "Episodic module missing"}}
        
        result = self.mem.save(content=content, importance=importance, tags=tags or [])
        
        # Atomic write confirmation
        if isinstance(result, dict) and "filepath" in result:
            atomic_json_write(Path(result["filepath"]), result.get("data", {}))
        
        return {"result": content[:100], "status": "success", "metadata": {"importance": importance, "tags": tags}}
    
    def recall(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        if not self.mem:
            return {"result": [], "status": "success", "metadata": {"note": "Episodic module missing"}}
        
        results = self.mem.recall(query=query, top_k=top_k)
        formatted = [{"content": str(item), "importance": 1} for item in (results if isinstance(results, list) else [results])]
        
        return {"result": formatted, "status": "success", "metadata": {"query": query, "returned": len(formatted)}}
