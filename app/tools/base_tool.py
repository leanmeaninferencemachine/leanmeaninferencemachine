# app/tools/base_tool.py
"""
Dynamic Tool Registry for LMIM/Horus
- Abstract base class for all tools
- Rate limiting + auth flags for safety
- Clear stub pattern for cross-agent tools
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
import json
import time
from pathlib import Path

class BaseTool(ABC):
    """Abstract Base Class for all LMIM/Horus Tools."""
    
    name: str = "base"
    description: str = "Base tool - override in subclass"
    args_schema: Optional[Dict[str, Any]] = None  # JSON Schema for model prompting
    
    # Safety & policy flags
    requires_auth: bool = False
    rate_limit: Optional[int] = None  # max calls per minute
    is_stub: bool = False  # Marks tools pending external integration
    
    def __init__(self):
        self.last_result: Optional[Dict[str, Any]] = None
        self._call_timestamps: List[float] = []
    
    def _check_rate_limit(self) -> bool:
        """Enforce rate limiting if configured."""
        if not self.rate_limit:
            return True
        
        now = time.time()
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 60]
        
        if len(self._call_timestamps) >= self.rate_limit:
            return False
        
        self._call_timestamps.append(now)
        return True
    
    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        pass
    
    def validate_input(self, kwargs: Dict) -> tuple[bool, Optional[str]]:
        if not self.args_schema:
            return True, None
        required = self.args_schema.get("required", [])
        for field in required:
            if field not in kwargs:
                return False, f"Missing required argument: {field}"
        return True, None
    
    def safe_execute(self, **kwargs) -> Dict[str, Any]:
        valid, error_msg = self.validate_input(kwargs)
        if not valid:
            return {"result": None, "status": "error", "error": error_msg}
        if not self._check_rate_limit():
            return {"result": None, "status": "error", "error": f"Rate limit exceeded ({self.rate_limit}/min)"}
        try:
            result = self.execute(**kwargs)
            self.last_result = result
            return result
        except Exception as e:
            return {"result": None, "status": "error", "error": str(e)}

# ─────────────────────────────────────────────────────────────
# CONCRETE TOOL IMPLEMENTATIONS (Stubs for Registry)
# ─────────────────────────────────────────────────────────────

class MemoryTool(BaseTool):
    name = "store_memory"
    description = "Save a fact or memory to the episodic store."
    args_schema = {"type": "object", "properties": {"content": {"type": "string"}, "importance": {"type": "integer"}}, "required": ["content"]}
    def execute(self, **kwargs): return {"result": "[TOOL] Memory stored", "status": "success"}

class RecallMemoryTool(BaseTool):
    name = "recall_memory"
    description = "Search stored memories."
    args_schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    def execute(self, **kwargs): return {"result": "[TOOL] Recall query", "status": "success"}

class SearchTool(BaseTool):
    name = "web_search"
    description = "Search the web."
    args_schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    rate_limit = 10
    def execute(self, **kwargs): return {"result": "[SEARCH] Query executed", "status": "success"}

class HorusStubTool(BaseTool):
    name = "scan_vulnerability"
    description = "[STUB] Request Horus engine scan."
    is_stub = True
    requires_auth = True
    args_schema = {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}
    def execute(self, **kwargs): return {"result": "[HORUS STUB] Scan requested", "status": "pending"}

# ─────────────────────────────────────────────────────────────
# TOOL REGISTRY
# ─────────────────────────────────────────────────────────────

TOOL_REGISTRY: Dict[str, BaseTool] = {
    "store_memory": MemoryTool(),
    "recall_memory": RecallMemoryTool(),
    "web_search": SearchTool(),
    "scan_vulnerability": HorusStubTool(),
}

def get_tool_schema(tool_name: str) -> Optional[Dict[str, Any]]:
    tool = TOOL_REGISTRY.get(tool_name)
    if tool and tool.args_schema:
        return {"name": tool.name, "description": tool.description, "parameters": tool.args_schema}
    return None

def list_available_tools(include_stubs: bool = False) -> List[Dict[str, str]]:
    return [{"name": t.name, "description": t.description, "stub": t.is_stub} for t in TOOL_REGISTRY.values() if include_stubs or not t.is_stub]
