# app/workers/builder.py — BuilderWorker: handles BUILD_REQUEST events
import os
import json
import logging
import subprocess
import time
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from app.events.base import EventType, Event
from app.model_interface import query_model
from app.config import BUILDER_CODE_GEN_PROMPT, BUILDER_CODE_FIX_PROMPT
from app.agents.inspector import inspect_and_patch, apply_patch

logger = logging.getLogger(__name__)

# 🔥 CRITICAL: Dynamic Path Resolution for AppImage
def get_writable_workspace() -> Path:
    """Returns the writable workspace directory (Home Dir for AppImage)."""
    env_path = os.getenv('LMIM_DATA_DIR')
    if env_path:
        ws = Path(env_path) / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        return ws
    # Fallback to local project workspace
    if getattr(sys, 'frozen', False):
        ws = Path.home() / ".lmim_os" / "workspace"
    else:
        ws = Path(__file__).resolve().parent.parent.parent / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws

# Define Global Paths Immediately
WORKSPACE_ROOT = get_writable_workspace()
DEFAULT_MAX_ATTEMPTS = 10

logger.info(f"✅ [BUILDER] Workspace set to: {WORKSPACE_ROOT}")

def _detect_filename(spec: str) -> str:
    """Intelligently detect target filename from spec."""
    spec_lower = spec.lower()
    if "requirements.txt" in spec_lower: return "requirements.txt"
    elif "readme.md" in spec_lower: return "README.md"
    elif "tests.py" in spec_lower or "test_" in spec_lower: return "tests.py"
    elif "processor.py" in spec_lower: return "processor.py"
    elif "main.py" in spec_lower: return "main.py"
    else: return "solution.py"

def _detect_test_command(filename: str) -> str:
    """Determine test command based on file extension."""
    if filename.endswith(".txt") or filename.endswith(".md"):
        return f"cat {filename}"
    elif filename.endswith(".py"):
        # ✅ SAFE MODE: Syntax Check Only
        return f"python3 -m py_compile {filename}"
    else:
        return f"cat {filename}"

def _extract_clean_code(raw: str) -> str:
    """Extract pure Python code, stripping markdown, explanations, and tool markers."""
    # 1. Remove Tool Markers
    raw = re.sub(r'\[TOOL_CALL\].*?(\[/TOOL_CALL\])?', '', raw, flags=re.DOTALL)
    
    # 2. Remove Markdown Blocks
    pattern = r'```python\s*\n(.*?)\n```'
    markdown_match = re.search(pattern, raw, re.DOTALL)
    if markdown_match:
        code = markdown_match.group(1)
    else:
        code = re.sub(r'```[a-z]*\n?', '', raw)
    
    # 3. Aggressive Line-by-Line Cleaning
    lines = code.split('\n')
    cleaned = []
    in_code = False
    skip_phrases = [
        'here is', "here's", 'i have', 'try this', 'corrected:', 'fixed:', 
        'got it', 'sure', 'okay', 'this simple', 'this function', 'just returns',
        'you can call', 'example usage', 'note that', 'remember that', 'no external'
    ]
    
    for line in lines:
        stripped = line.strip().lower()
        
        # Skip intro phrases
        if any(stripped.startswith(p) for p in skip_phrases):
            continue
        if stripped in ['python', 'code:', 'output:', 'result:', '']:
            continue
        
        # Detect code start
        if not in_code:
            if any(line.strip().startswith(k) for k in ('import ', 'from ', 'def ', 'class ', 'if ', 'for ', 'while ', 'return ', 'elif ', 'else:', 'try:', 'except', 'with ', 'assert ', 'print(', '"""', "'''", '#')):
                in_code = True
            elif any(c in line for c in '(){}[]=+-*/<>'):
                in_code = True
        
        if in_code:
            cleaned.append(line)
        elif line.strip() == '' and cleaned: # Keep empty lines inside code
            cleaned.append(line)
            
    result = '\n'.join(cleaned).strip()
    return result if result else raw.strip()

def _save_debug_backup(workspace: Path, filename: str, content: str, attempt: int, stage: str):
    """Save a copy of the generation to workspace/debug/ for inspection."""
    debug_dir = workspace / "debug"
    debug_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(filename).stem
    suffix = Path(filename).suffix
    backup_file = debug_dir / f"{base_name}_attempt_{attempt}_{stage}_{timestamp}{suffix}"
    try:
        with open(backup_file, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"💾 Debug Backup Saved: {backup_file.name} ({len(content)} chars)")
    except Exception as e:
        logger.warning(f"Failed to save debug backup: {e}")

def _backup_attempt(workspace: Path, filename: str, content: str, attempt: int):
    """Legacy alias for _save_debug_backup."""
    _save_debug_backup(workspace, filename, content, attempt, "raw")

class BuilderWorker:
    """Background worker with auto-debug retry loop."""
    
    def __init__(self, workspace_root: str = None, event_bus=None):
        # Use dynamic workspace if not explicitly overridden
        self.workspace = Path(workspace_root) if workspace_root else WORKSPACE_ROOT
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.event_bus = event_bus
        self._build_cache = {}
        logger.info(f"BuilderWorker initialized (workspace: {self.workspace})")
    
    def _create_file(self, file_path: str, content: str, task_id: str) -> bool:
        try:
            # Sanitize: Remove 'workspace/' prefix if present
            if file_path.startswith('workspace/'):
                file_path = file_path[len('workspace/'):]
            target = (self.workspace / file_path).resolve()
            
            # Security Check
            if not str(target).startswith(str(self.workspace)):
                logger.error(f"Path traversal blocked: {file_path}")
                return False
                
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"📝 Created file: {file_path} (task: {task_id})")
            return True
        except Exception as e:
            logger.error(f"File creation failed: {e}")
            return False
    
    def _run_command(self, command: str, task_id: str, timeout: int = None) -> Tuple[bool, str]:
        timeout = timeout or int(os.getenv("BUILDER_CMD_TIMEOUT", "300"))
        try:
            allowed = ['python3 ', 'python -m ', 'pip install ', 'cat ', 'ls ', 'pytest ']
            if not any(command.startswith(p) for p in allowed):
                return False, "Command not allowed"
            
            # FIX: Handle 'python3 -c "..."' commands correctly
            if 'python3 -c "' in command or "python3 -c '" in command:
                args = shlex.split(command)
            else:
                args = command.split()
            
            # CRITICAL FIX: Run from PROJECT ROOT, not workspace.
            # self.workspace is .../workspace
            # self.workspace.parent is .../ (Project Root) -> Ensures 'app' module is discoverable
            result = subprocess.run(
                args, cwd=str(self.workspace.parent), capture_output=True, text=True, timeout=timeout
            )
            success = (result.returncode == 0)
            output = result.stdout.strip() or result.stderr.strip()
            
            if success:
                logger.debug(f"✅ Command OK: {command[:50]}...")
            else:
                logger.debug(f"❌ Command Fail: {command[:50]}... error: {output[:100]}")
                
            return success, output
        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)
    
    def _emit_step(self, event_type: EventType, task_id: str, payload: dict):
        """Helper to emit events with consistent structure."""
        if self.event_bus:
            self.event_bus.publish_sync(Event(
                type=event_type,
                payload={'task_id': task_id, **payload},
                source="builder_worker"
            ))
    
    async def _handle_build_request(self, event: Event) -> Dict[str, Any]:
        """Process BUILD_REQUEST with auto-debug retry loop."""
        payload = event.payload
        task_id = payload.get('task_id')
        spec = payload.get('description')
        user_id = payload.get('user_id', 'unknown')
        language = payload.get('language', 'python')
        
        # 🔥 DYNAMIC FILENAME DETECTION
        filename = payload.get("filename")
        if not filename:
            filename = _detect_filename(spec)
            logger.warning(f"⚠️ Filename missing from payload, detected: {filename}")
        else:
            logger.info(f"✅ Using explicit filename from payload: {filename}")
            
        # Sanitize filename
        if filename.startswith('workspace/'):
            filename = filename[len('workspace/'):]
            
        test_command = _detect_test_command(filename)
        
        logger.info(f"🔨 Build started: task={task_id}, target={filename}, cmd={test_command}")
        self._build_cache[task_id] = {'status': 'processing', 'attempts': 0}
        
        last_code = ""
        last_error = ""
        
        for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
            self._build_cache[task_id]['attempts'] = attempt
            logger.info(f"🔄 Agent step {attempt}/{DEFAULT_MAX_ATTEMPTS}")
            
            try:
                # Format prompt
                if attempt == 1:
                    full_prompt = BUILDER_CODE_GEN_PROMPT.format(
                        language=language, spec=spec, test_command=test_command
                    )
                else:
                    full_prompt = BUILDER_CODE_FIX_PROMPT.format(
                        language=language, spec=spec,
                        previous_code=last_code[:1000],
                        error=last_error[:500]
                    )
                
                # Call model
                raw_model_output = query_model(
                    prompt=full_prompt,
                    user_id=user_id,
                    builder_mode=True
                )
                
                # 🔥 DEBUG: Save RAW output
                _save_debug_backup(self.workspace, filename, raw_model_output, attempt, "raw")
                
                # Sanitize
                code = _extract_clean_code(raw_model_output)
                
                logger.info(f"📊 Extraction Stats: Raw={len(raw_model_output)} → Clean={len(code)}")
                if len(code) < 50:
                    logger.warning(f"⚠️ CRITICAL: Extracted code is very short ({len(code)} chars).")
                
                # 🔥 DEBUG: Save CLEAN output
                _save_debug_backup(self.workspace, filename, code, attempt, "clean")
                
                last_code = code
                _backup_attempt(self.workspace, filename, code, attempt)
                
                # Write file
                if not self._create_file(filename, code, task_id):
                    raise RuntimeError("File creation failed")
                
                self._emit_step(EventType.BUILD_STEP_COMPLETE, task_id, {
                    'attempt': attempt, 'file': filename, 'status': 'generated'
                })
                
                # Test execution
                if filename.endswith(".py"):
                    # 1. Syntax Check
                    success, output = self._run_command(test_command, task_id, timeout=int(os.getenv("BUILDER_CMD_TIMEOUT", "300")))

                    # 🔥 RUNTIME EXECUTION HOOK (Disabled by default, enable for specific files)
                    # if False and filename.endswith("main.py"): 
                    #     logger.info(f"🏃 Attempting RUNTIME EXECUTION...")
                    #     run_cmd = f"python3 {filename}"
                    #     run_success, run_output = self._run_command(run_cmd, task_id, timeout=30)
                    #     if not run_success:
                    #         success = False
                    #         output = f"SYNTAX OK, BUT RUNTIME ERROR:\n{run_output}"
                    
                    self._emit_step(EventType.TOOL_RESULT, task_id, {
                        'attempt': attempt, 'command': test_command,
                        'success': success, 'output': output[:200]
                    })
                    
                    if success:
                        logger.info(f"✅ Syntax Check Passed.")
                        
                        # 🔥 INTEGRATION TEST HOOK
                        main_path = self.workspace / "main.py"
                        if main_path.exists() and filename != "main.py":
                            logger.info("🧪 Running Integration Test: python3 main.py...")
                            int_success, int_output = self._run_command("python3 main.py", task_id, timeout=10)
                            
                            if not int_success:
                                logger.warning("💥 Integration Test FAILED!")
                                last_error = "SYNTAX OK, but INTEGRATION TEST FAILED:\n" + int_output
                                continue # Retry
                            else:
                                logger.info("🎉 Integration Test PASSED!")
                                output = output + "\n[INTEGRATION TEST]:\n" + int_output

                        self._build_cache[task_id] = {
                            'status': 'success', 'file_path': str(self.workspace / filename),
                            'attempts': attempt, 'output': output[:500]
                        }
                        self._emit_step(EventType.BUILD_SUCCESS, task_id, {
                            'file': filename, 'attempts': attempt
                        })
                        logger.info(f"✅ Agent succeeded on attempt {attempt}")
                        return {'status': 'success', 'file': filename, 'attempts': attempt}

                    else:
                        logger.warning(f"❌ Attempt {attempt} failed: {output[:100]}...")
                        last_error = output
                else:
                    # Non-Python
                    logger.info(f"✅ Non-Python file created: {filename}")
                    self._build_cache[task_id] = {
                        'status': 'success', 'file_path': str(self.workspace / filename), 
                        'attempts': attempt
                    }
                    self._emit_step(EventType.BUILD_SUCCESS, task_id, {'file': filename, 'attempts': attempt})
                    return {'status': 'success', 'file': filename, 'attempts': attempt}
                    
            except Exception as e:
                logger.error(f"💥 Attempt {attempt} error: {e}", exc_info=True)
                last_error = str(e)
                self._emit_step(EventType.BUILD_STEP_COMPLETE, task_id, {
                    'attempt': attempt, 'error': str(e)[:200]
                })
                continue
        
        # All attempts failed
        logger.error(f"💥 Agent failed after {DEFAULT_MAX_ATTEMPTS} attempts")
        self._build_cache[task_id] = {
            'status': 'failed', 'error': 'Max attempts reached',
            'last_error': last_error[:500]
        }
        self._emit_step(EventType.BUILD_ERROR, task_id, {
            'error': 'Max attempts reached', 'last_error': last_error[:200]
        })
        return {'status': 'failed', 'error': 'Max attempts reached', 'attempts': DEFAULT_MAX_ATTEMPTS}
    
    def get_status(self, task_id: str) -> dict:
        return self._build_cache.get(task_id, {'status': 'not_found'})

# Global instance
_builder_worker = None

def init_builder_worker(event_bus):
    global _builder_worker
    _builder_worker = BuilderWorker(event_bus=event_bus)
    if event_bus:
        event_bus.subscribe(EventType.BUILD_REQUEST, _builder_worker._handle_build_request, priority=10)
        logger.debug("BuilderWorker handlers registered")
    return _builder_worker

def get_builder_worker():
    return _builder_worker
