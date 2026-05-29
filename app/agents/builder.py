# app/agents/builder.py
import logging
import re
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING

from app.agents.base import BaseAgent
from app.model_interface import query_model
from app.config import BUILDER_CODE_GEN_PROMPT, BUILDER_CODE_FIX_PROMPT

if TYPE_CHECKING:
    from app.workers.builder import BuilderWorker

logger = logging.getLogger(__name__)

class BuilderAgent(BaseAgent):
    """Autonomous code builder: generate → test → debug → fix."""
    
    def __init__(
        self, 
        builder_worker: "BuilderWorker",
        user_id: str,
        language: str = "python",
        max_attempts: int = 3,
        test_command: Optional[str] = None,
        filename: Optional[str] = None
    ):
        super().__init__(max_attempts=max_attempts)
        self.builder = builder_worker
        self.user_id = user_id
        self.language = language
        
        # --- DYNAMIC FILENAME LOGIC ---
        if filename:
            self.filename = filename
        else:
            self.filename = "solution.py" if language == "python" else f"solution.{language}"
        
        # --- SMART TEST COMMAND LOGIC ---
        if self.filename.endswith(".txt") or self.filename.endswith(".md"):
            self.test_command = f"cat {self.filename}"
        else:
            self.test_command = test_command or f"python3 {self.filename}"
            
        logger.info(f"🔨 BuilderAgent initialized: file={self.filename}, cmd={self.test_command}")
        
    async def generate(self, context: Dict) -> str:
        """Generate code using the LLM with builder-specific prompts."""
        attempt = context.get("attempt", 0)
        
        if attempt == 0:
            prompt = BUILDER_CODE_GEN_PROMPT.format(
                language=self.language,
                spec=context["spec"],
                test_command=self.test_command
            )
        else:
            prompt = BUILDER_CODE_FIX_PROMPT.format(
                language=self.language,
                spec=context["spec"],
                previous_code=context.get("generated_output", ""),
                error=context.get("previous_error", "Unknown error")
            )
        
        reply = query_model(prompt=prompt, user_id=self.user_id, builder_mode=True)
        code = self._extract_code(reply)
        logger.debug(f"Generated code ({len(code)} chars): {code[:100]}...")
        return code
    
    def _extract_code(self, raw: str) -> str:
        """Extract pure code while preserving indentation."""
        code = raw
        pattern = r'```(?:python|py)?\s*(.*?)```'
        markdown_match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        
        if markdown_match:
            code = markdown_match.group(1).strip()
        else:
            code = re.sub(r'```[a-z]*\n?', '', raw, flags=re.IGNORECASE)
            code = code.strip()
        
        lines = code.split('\n')
        cleaned = []
        in_code = False
        code_start_keywords = ('import ', 'from ', 'def ', 'class ', '@', 'if __name__', 'try:', 'except ', 'with ', 'assert ', 'print(', '#')
        
        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()
            if not stripped and not in_code:
                continue
            if not in_code:
                if re.match(r'^[\w_]+\.(py|txt|md)\s*[-–:]', stripped):
                    continue
                if any(lower.startswith(p) for p in ['here is', "here's", 'i have', 'try this', 'corrected:', 'fixed:', 'got it', 'sure', 'okay', 'this script', 'no external']):
                    continue
                if any(stripped.startswith(k) for k in code_start_keywords):
                    in_code = True
                elif stripped.startswith('"""') or stripped.startswith("'''"):
                    in_code = True
                else:
                    continue
            if in_code:
                cleaned.append(line)
        
        result = '\n'.join(cleaned).strip()
        if result:
            final_lines = result.split('\n')
            while final_lines:
                first = final_lines[0].strip()
                if any(first.startswith(k) for k in code_start_keywords) or first.startswith('"""') or first.startswith("'''"):
                    break
                final_lines.pop(0)
            result = '\n'.join(final_lines)
            
        return result if result else raw.strip()
    
    async def execute(self, code: str) -> Dict[str, Any]:
        """Write code and run test command."""
        # The Worker (_create_file) must be initialized with DATA_DIR in main.py
        write_result = await self.builder._create_file(self.filename, code)
        if not write_result.get("path"):
            return {"success": False, "error": "Failed to write file"}
        return await self.builder._run_command(self.test_command, timeout=10)
    
    def is_success(self, result: Dict) -> bool:
        """Check execution success."""
        return result.get("success") is True and result.get("returncode") == 0
