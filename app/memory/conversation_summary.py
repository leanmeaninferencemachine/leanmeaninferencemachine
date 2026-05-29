# app/memory/conversation_summary.py
import logging
import time
import json
from pathlib import Path
from typing import List, Optional, Dict

from app.config import SUMMARY_INTERVAL, SUMMARY_MAX_HISTORY_TURNS

logger = logging.getLogger(__name__)

class ConversationSummary:
    """Manages conversation summarization with PERSISTENCE to disk."""
    
    def __init__(self, user_id: str, summary_interval: int = None, max_history_turns: int = None, memory_dir: Path = None):
        self.user_id = user_id
        self.summary_interval = summary_interval or SUMMARY_INTERVAL
        self.max_history_turns = max_history_turns or SUMMARY_MAX_HISTORY_TURNS
        
        # 🔥 GESTIÓN DE RUTAS EXPLÍCITAS
        if memory_dir:
            self.base_dir = memory_dir
        else:
            # Fallback legacy (carpeta por usuario si no se pasa ruta)
            self.base_dir = Path(f"data/memories/users/{user_id}")
            
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Rutas de archivos en disco
        self.summary_file = self.base_dir / "summary_full.json"
        self.history_file = self.base_dir / "chat_history.json"
        
        # Cache en memoria (se carga al inicio si existe)
        self.summary: Optional[str] = None
        self.summary_meta: Dict = {}
        self._load_from_disk()

    def _load_from_disk(self):
        """Carga el resumen guardado en disco al iniciar."""
        if self.summary_file.exists():
            try:
                with open(self.summary_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.summary = data.get("content", "")
                self.summary_meta = data.get("meta", {})
                logger.debug(f"📖 Loaded summary from disk for {self.user_id}")
            except Exception as e:
                logger.warning(f"Could not load summary from disk: {e}")
        else:
            logger.debug(f"ℹ️ No summary file found for {self.user_id}")

    def should_summarize(self, turn_count: int) -> bool:
        return turn_count > 0 and turn_count % self.summary_interval == 0
    
    def generate_summary_prompt(self, recent_turns: List) -> str:
        """Create a prompt for the model to summarize conversation."""
        def _fmt(turn):
            if isinstance(turn, dict):
                return f"{turn.get('role', 'unknown')}: {turn.get('content', '')}"
            elif isinstance(turn, (tuple, list)) and len(turn) >= 2:
                return f"{turn[0]}: {turn[1]}"
            return str(turn)
        
        # Tomar últimos 20 turns para resumir
        turns_text = "\n".join([_fmt(t) for t in recent_turns[-20:]])
        
        return f"""Summarize this conversation in detail (3-5 sentences). Focus on:
1. Main topics discussed
2. Decisions made or action items
3. User preferences or key facts revealed

Conversation History:
{turns_text}

Detailed Summary:""".strip()
    
    def store_summary(self, summary_text: str, meta: Dict = None):
        """Guarda en memoria Y en disco inmediatamente."""
        self.summary = summary_text.strip()
        self.summary_meta = meta or {}
        self.summary_meta["created_at"] = time.time()
        
        # 🔥 ESCRITURA EN DISCO
        data = {
            "content": self.summary,
            "meta": self.summary_meta,
            "user_id": self.user_id
        }
        
        try:
            with open(self.summary_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"💾 Summary persisted to: {self.summary_file.absolute()}")
        except Exception as e:
            logger.error(f"Failed to write summary to disk: {e}")
    
    def get_stored_summary(self) -> str:
        """Devuelve el resumen cargado (de memoria o disco)."""
        # Si no está en memoria, intentar recargar de disco por seguridad
        if not self.summary and self.summary_file.exists():
            self._load_from_disk()
        return self.summary or ""

    def get_context(self, recent_turns: List) -> str:
        """Formato legacy para inyección directa (si se usara)."""
        # Esta función ya no la usamos tanto con la nueva arquitectura de ventana deslizante,
        # pero la dejamos por compatibilidad.
        if not recent_turns:
            return self.summary or ""
        
        def _format_turn(turn):
            if isinstance(turn, dict):
                return f"{turn.get('role', 'unknown')}: {turn.get('content', '')}"
            return str(turn)
        
        recent_text = "\n".join([_format_turn(t) for t in recent_turns[-self.max_history_turns:]])
        
        if self.summary:
            return f"📋 SUMMARY: {self.summary}\n\n--- RECENT ---\n{recent_text}"
        return recent_text