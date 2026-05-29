# app/agents/base.py
import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class BaseAgent(ABC):
    """
    Base class for autonomous agents.
    Handles: retry loops, error context, success detection.
    """
    
    def __init__(self, max_attempts: int = 3, timeout_per_step: int = 30):
        self.max_attempts = max_attempts
        self.timeout_per_step = timeout_per_step
        self.state: Dict[str, Any] = {}
        
    @abstractmethod
    async def generate(self, context: Dict) -> str:
        """Generate output (code, answer, etc.) from context. Must be implemented."""
        pass
    
    @abstractmethod
    async def execute(self, output: str) -> Dict[str, Any]:
        """Execute the generated output. Return result dict with 'success' key."""
        pass
    
    @abstractmethod
    def is_success(self, result: Dict) -> bool:
        """Determine if execution succeeded."""
        pass
    
    async def run(self, initial_context: Dict, on_step: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Main loop: generate → execute → evaluate → (fix if needed) → repeat.
        
        Args:
            initial_context: Starting spec/task for the agent
            on_step: Optional callback for progress updates (event emission)
            
        Returns:
            Dict with 'success', 'output', 'attempts', 'errors' keys
        """
        context = initial_context.copy()
        errors = []
        
        for attempt in range(1, self.max_attempts + 1):
            logger.info(f"🔄 Agent step {attempt}/{self.max_attempts}")
            
            # 1. Generate
            output = await self.generate(context)
            context["generated_output"] = output
            
            if on_step:
                await on_step("generate", {"attempt": attempt, "output_preview": output[:200]})
            
            # 2. Execute
            try:
                result = await asyncio.wait_for(
                    self.execute(output), 
                    timeout=self.timeout_per_step
                )
            except asyncio.TimeoutError:
                result = {"success": False, "error": f"Timeout after {self.timeout_per_step}s"}
            
            context["last_result"] = result
            
            if on_step:
                await on_step("execute", {"attempt": attempt, "result": result})
            
            # 3. Evaluate
            if self.is_success(result):
                logger.info(f"✅ Agent succeeded on attempt {attempt}")
                return {
                    "success": True,
                    "output": output,
                    "result": result,
                    "attempts": attempt,
                    "errors": errors
                }
            
            # 4. Prepare for retry
            error_info = result.get("error") or result.get("stderr", "Unknown error")
            errors.append({"attempt": attempt, "error": error_info})
            context["previous_error"] = error_info
            context["attempt"] = attempt
            
            logger.warning(f"❌ Attempt {attempt} failed: {error_info[:100]}...")
        
        # Max attempts reached
        logger.error(f"💥 Agent failed after {self.max_attempts} attempts")
        return {
            "success": False,
            "output": context.get("generated_output"),
            "attempts": self.max_attempts,
            "errors": errors
        }
