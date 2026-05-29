# app/memory_functions.py
import json
import os
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict
from collections import defaultdict

# 🔥 CRITICAL SAFETY CHECK: Override MEMORY_DIR if running in AppImage
# This ensures we always write to ~/.lmim_os even if config.py hasn't loaded yet.
env_data_dir = os.getenv('LMIM_DATA_DIR')
if env_data_dir:
    MEMORY_DIR = os.path.join(env_data_dir, "memories")
else:
    # Fallback to config default if env var not set
    from app.config import MEMORY_DIR as CONFIG_MEMORY_DIR
    MEMORY_DIR = CONFIG_MEMORY_DIR

from app.config import (
    MAX_MEMORIES_PER_USER, MEMORY_RETRIEVAL_TOP_K, 
    PERSISTENT_MEMORY_ENABLED, ENABLE_AUDIT_LOGGING
)

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit") if ENABLE_AUDIT_LOGGING else None

_session_cache = defaultdict(list)

def _get_user_dir(user_id: str) -> Path:
    """🔥 CLAVE: Obtiene y ASEGURA la existencia del directorio: {DATA_DIR}/memories/users/{user_id}/"""
    base_dir = Path(MEMORY_DIR) / "users"
    user_dir = base_dir / user_id
    
    # Forzar creación si no existe
    if not user_dir.exists():
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
            logger.debug(f"📂 Created user directory: {user_dir}")
        except Exception as e:
            logger.error(f"❌ Failed to create user directory {user_dir}: {e}")
            
    return user_dir

def update_session_memory(user: str, message: str, reply: str, max_turns: int = 12):
    """Update in-memory conversation history."""
    _session_cache[user].append({"role": "user", "content": message})
    _session_cache[user].append({"role": "assistant", "content": reply})
    if len(_session_cache[user]) > max_turns * 2:
        _session_cache[user] = _session_cache[user][-max_turns * 2:]
    logger.debug(f"Session cache updated: user={user}, turns={len(_session_cache[user])//2}")

def get_session_context(user: str) -> str:
    return "\n".join(f"{m['role']}: {m['content']}" for m in _session_cache[user])

# === PERSISTENT MEMORY ===

def _load_user_memories_file(user_id: str) -> List[Dict]:
    """Carga desde: users/{user_id}/memories.json"""
    if not PERSISTENT_MEMORY_ENABLED: return []
    
    user_dir = _get_user_dir(user_id)
    path = user_dir / "memories.json"
    
    # Fallback legacy (check relative to MEMORY_DIR just in case)
    if not path.exists():
        legacy_path = Path(MEMORY_DIR) / "users" / f"{user_id}.json"
        if legacy_path.exists():
            try:
                logger.warning(f"⚠️ Loading LEGACY memory file: {legacy_path}")
                with open(legacy_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("memories", [])
            except Exception as e:
                logger.error(f"Failed to load legacy file: {e}")
        return []
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("memories", [])
    except Exception as e:
        logger.error(f"Failed to load user memories from {path}: {e}")
        return []

def _save_user_memories_file(user_id: str, memories: List[Dict]):
    """Guarda en: users/{user_id}/memories.json"""
    if not PERSISTENT_MEMORY_ENABLED: return
    
    user_dir = _get_user_dir(user_id)
    path = user_dir / "memories.json"
    
    # Doble verificación de que el directorio existe
    try:
        user_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"❌ CRITICAL: Cannot create directory {user_dir}: {e}")
        return

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"memories": memories, "last_updated": time.time()}, f, indent=2, ensure_ascii=False)
        logger.debug(f"💾 SUCCESS: Saved user memories to {path}")
    except IOError as e:
        logger.error(f"❌ IO Error saving memories to {path}: {e}")
    except Exception as e:
        logger.error(f"❌ Unexpected error saving memories: {e}", exc_info=True)

# === CHAT HISTORY ===

def log_whatsapp_chat_turn(user_id: str, user_msg: str, ai_reply: str, max_turns: int = 20):
    """Loguea en: users/{user_id}/chat_history.json"""
    if not PERSISTENT_MEMORY_ENABLED: return

    user_dir = _get_user_dir(user_id)
    chat_file = user_dir / "chat_history.json"

    history = []
    if chat_file.exists():
        try:
            with open(chat_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                history = data.get("messages", [])
        except Exception as e:
            logger.warning(f"Could not read chat history, starting fresh: {e}")
            history = []

    timestamp = time.time()
    history.append({"role": "user", "content": user_msg, "timestamp": timestamp})
    history.append({"role": "assistant", "content": ai_reply, "timestamp": timestamp})
    
    if len(history) > max_turns * 2:
        history = history[-(max_turns * 2):]

    try:
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump({"user_id": user_id, "messages": history}, f, indent=2, ensure_ascii=False)
        logger.debug(f"📝 Logged chat turn to {chat_file}")
    except Exception as e:
        logger.error(f"Failed to log chat turn: {e}")

def get_recent_chat_history(user_id: str, limit: int = 10) -> list:
    """Lee desde: users/{user_id}/chat_history.json"""
    user_dir = _get_user_dir(user_id)
    chat_file = user_dir / "chat_history.json"
    
    if not chat_file.exists():
        legacy_file = Path(MEMORY_DIR) / "users" / f"{user_id}_chat.json"
        if legacy_file.exists():
            try:
                logger.warning(f"⚠️ Loading LEGACY chat file: {legacy_file}")
                with open(legacy_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("messages", [])
            except: pass
        return []
    
    try:
        with open(chat_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("messages", [])[-(limit * 2):]
    except Exception:
        return []

# === GLOBAL MEMORY ===
def _get_global_path() -> Path:
    return Path(MEMORY_DIR) / "global.json"

def _load_global_memories() -> List[Dict]:
    if not PERSISTENT_MEMORY_ENABLED: return []
    path = _get_global_path()
    if not path.exists(): return []
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f).get("memories", [])
    except: return []

def _save_global_memories(memories: List[Dict]):
    if not PERSISTENT_MEMORY_ENABLED: return
    path = _get_global_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"memories": memories, "last_updated": time.time()}, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error(f"Failed to save global memories: {e}")

# === HELPERS ===

def _store_user_memory(user_id: str, key: str, value: str, metadata: Optional[Dict] = None) -> bool:
    if not PERSISTENT_MEMORY_ENABLED: 
        logger.warning("Persistent memory disabled.")
        return False
    
    memories = _load_user_memories_file(user_id)
    # Eliminar duplicados por clave
    memories = [m for m in memories if m.get("key") != key]
    
    # Normalizar tags
    if metadata and "tags" in metadata:
        tags = metadata["tags"]
        if isinstance(tags, str): tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list): tags = [str(t).strip().lower() for t in tags if str(t).strip()]
        else: tags = []
        metadata["tags"] = tags
    elif metadata is None: metadata = {"tags": []}
    elif "tags" not in metadata: metadata["tags"] = []
    
    memories.append({
        "key": key, "value": value,
        "metadata": {**metadata, "created_at": time.time()}
    })
    
    if len(memories) > MAX_MEMORIES_PER_USER:
        memories = memories[-MAX_MEMORIES_PER_USER:]
    
    # Intentar guardar
    user_dir = _get_user_dir(user_id)
    path = user_dir / "memories.json"
    logger.debug(f"Attempting to save {len(memories)} memories to {path}")
    
    try:
        _save_user_memories_file(user_id, memories)
        # Verificar si realmente se guardó (lectura rápida)
        if path.exists():
            if audit_logger and ENABLE_AUDIT_LOGGING:
                audit_logger.info(json.dumps({
                    "timestamp": time.time(), "user": user_id, "operation": "store_memory",
                    "key": key, "scope": "user", "success": True
                }))
            return True
        else:
            logger.error(f"File {path} does not exist after save attempt.")
            return False
    except Exception as e:
        logger.error(f"Exception during store: {e}")
        return False

def _store_global_memory(key: str, value: str, metadata: Optional[Dict] = None) -> bool:
    if not PERSISTENT_MEMORY_ENABLED: return False
    memories = _load_global_memories()
    memories = [m for m in memories if m.get("key") != key]
    
    if metadata and "tags" in metadata:
        tags = metadata["tags"]
        if isinstance(tags, str): tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list): tags = [str(t).strip().lower() for t in tags if str(t).strip()]
        else: tags = []
        metadata["tags"] = tags
    elif metadata is None: metadata = {"tags": []}
    elif "tags" not in metadata: metadata["tags"] = []

    memories.append({"key": key, "value": value, "metadata": {**metadata, "created_at": time.time()}})
    if len(memories) > MAX_MEMORIES_PER_USER: memories = memories[-MAX_MEMORIES_PER_USER:]
    
    success = _save_global_memories(memories)
    if audit_logger and ENABLE_AUDIT_LOGGING:
        audit_logger.info(json.dumps({
            "timestamp": time.time(), "user": "global", "operation": "store_memory",
            "key": key, "scope": "global", "success": success
        }))
    return success

def _score_memories(memories: List[Dict], query: str, top_k: int) -> List[Dict]:
    if not memories: return []
    query_lower = query.lower().strip()
    if query_lower.startswith("key:"):
        target_key = query_lower[4:].strip()
        for m in memories:
            if m.get("key", "").lower() == target_key: return [m]
        return []
    
    query_words = set(query_lower.split())
    scored = []
    
    for i, m in enumerate(memories):
        key = m.get("key", "").lower()
        value = m.get("value", "").lower()
        tags = m.get("metadata", {}).get("tags", [])
        tags_lower = [str(t).lower() for t in tags]
        
        searchable = f"{key} {value} {' '.join(tags_lower)}"
        score = 0
        text_words = set(searchable.split())
        
        for word in list(text_words):
            if '_' in word and len(word) > 3:
                for part in word.split('_'): text_words.add(part.lower())
        
        exact_matches = query_words & text_words
        if exact_matches: score += len(exact_matches) * 2
        
        for qw in query_words:
            if len(qw) <= 2: continue
            if qw in key or qw in value or any(qw in t for t in tags_lower): score += 1
            elif any((qw in tw or tw in qw) and abs(len(qw) - len(tw)) <= 2 for tw in text_words if len(tw) > 2): score += 0.5
        
        if score > 0:
            recency = m.get("metadata", {}).get("created_at", 0) / (time.time() + 1)
            scored.append((score + 0.05 * recency, m))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:top_k]]

# === PUBLIC API ===

def store_memory(key: str, value: str, user_id: Optional[str] = None, 
                 metadata: Optional[Dict] = None, scope: str = "user") -> bool:
    logger.info(f"store_memory called: key='{key}', user='{user_id}', scope='{scope}'")
    if scope == "global" or not user_id:
        return _store_global_memory(key, value, metadata)
    return _store_user_memory(user_id, key, value, metadata)

def recall_memories(query: str, user_id: Optional[str] = None, 
                    top_k: Optional[int] = None, scope: str = "user") -> List[Dict]:
    if not PERSISTENT_MEMORY_ENABLED: return []
    top_k = top_k or MEMORY_RETRIEVAL_TOP_K
    
    if scope == "global":
        memories = _load_global_memories()
        return _score_memories(memories, query, top_k)
    else:
        if not user_id: return []
        memories = _load_user_memories_file(user_id)
        results = _score_memories(memories, query, top_k)
        
        if not results and query.lower() in ["what do you remember", "todo", "all", "sobre mí", "qué recuerdas"]:
            return memories[-top_k:] if len(memories) > top_k else memories
            
        return results
