import json
import logging
import re
from typing import Dict, Any, Optional
import requests
from app.config import LLM_API_URL, MODEL_NAME, PLANNER_API_TIMEOUT, INSPECTOR_PROMPT

logger = logging.getLogger(__name__)

def _repair_json(raw: str) -> Optional[Dict[str, Any]]:
    """Aggressive JSON repair for small models."""
    # 1. Strip markdown
    clean = re.sub(r'```json\s*', '', raw, flags=re.I)
    clean = re.sub(r'```\s*', '', clean)
    
    # 2. Extract JSON block
    match = re.search(r'\{.*\}', clean, re.DOTALL)
    if not match:
        return None
    
    candidate = match.group()
    
    # 3. Fix common issues
    # Remove trailing commas before } or ]
    candidate = re.sub(r',\s*([}\]])', r'\1', candidate)
    # Add quotes to unquoted keys (e.g., problem: -> "problem":)
    candidate = re.sub(r'(?<![{\[,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r' "\1":', candidate)
    # Replace single quotes with double quotes for strings
    # Be careful not to replace inside escaped sequences
    candidate = re.sub(r"'([^']*)'", r'"\1"', candidate)
    
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        logger.debug(f"JSON repair failed for: {candidate[:100]}...")
        return None

def inspect_and_patch(file_path: str, file_content: str, error_log: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Analyze error and return a JSON patch instruction.
    Strategy: Identify specific lines to replace to minimize token usage and escape errors.
    """
    logger.info(f"🕵️‍♂️ Inspector analyzing: {file_path}...")
    
    # Truncate inputs to fit context window while keeping relevant info
    content_snippet = file_content[:2500] 
    error_snippet = error_log[:1000]
    
    prompt = INSPECTOR_PROMPT.format(
        file_path=file_path,
        file_content=content_snippet,
        error_log=error_snippet
    )
    
    try:
        resp = requests.post(
            LM_STUDIO_URL,
            json={
                "model": MODEL_NAME, 
                "messages": [
                    {"role": "system", "content": "You are a senior debugger. Output STRICT JSON only. No markdown."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1, # Low temp for deterministic output
                "max_tokens": 800
            },
            timeout=PLANNER_API_TIMEOUT
        )
        resp.raise_for_status()
        
        raw = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        logger.debug(f"Inspector raw: {raw[:200]}...")
        
        diagnosis = _repair_json(raw)
        
        if diagnosis:
            # Validate required keys
            required = ['problem', 'line_start', 'line_end', 'replacement_code']
            missing = [k for k in required if k not in diagnosis]
            
            if not missing:
                logger.info(f"✅ Patch Generated: {diagnosis['problem']} (Lines {diagnosis['line_start']}-{diagnosis['line_end']})")
                return diagnosis
            else:
                logger.warning(f"Inspector JSON missing keys: {missing}. Got: {list(diagnosis.keys())}")
                # Fallback: If we have a fix strategy but no lines, return None to force full rewrite
                return None
        else:
            logger.warning("Inspector failed to produce valid JSON.")
            return None
            
    except Exception as e:
        logger.error(f"💥 Inspector API error: {e}", exc_info=True)
        return None

def apply_patch(original_content: str, patch: Dict[str, Any]) -> str:
    """
    Apply a JSON patch to the original content.
    Handles both replacement and insertion safely.
    """
    lines = original_content.splitlines()
    
    # Convert 1-based (LLM) to 0-based (Python)
    start = patch.get('line_start', 1) - 1 
    end = patch.get('line_end', 1) - 1
    replacement = patch.get('replacement_code', '')
    
    # Safety bounds
    total_lines = len(lines)
    start = max(0, min(start, total_lines))
    
    # Handle insertion (if end < start, it means insert BEFORE start)
    if end < start:
        insert_idx = start
        new_lines = lines[:insert_idx] + replacement.splitlines() + lines[insert_idx:]
        logger.debug(f"Applied INSERTION at line {start+1}")
    else:
        # Ensure end doesn't exceed bounds
        end = max(start, min(end, total_lines - 1))
        new_lines = lines[:start] + replacement.splitlines() + lines[end+1:]
        logger.debug(f"Applied REPLACEMENT for lines {start+1} to {end+1}")
    
    return "\n".join(new_lines)
