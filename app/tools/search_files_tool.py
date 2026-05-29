# app/tools/search_files_tool.py
import os
import re
import fnmatch
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.workspace import get_workspace, safe_path
from app.tools.base_tool import BaseTool

logger = logging.getLogger(__name__)


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search for text inside files within the workspace. Returns matching file paths with line numbers and snippets."
    args_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Text or regex pattern to search for"},
            "file_pattern": {"type": "string", "description": "Glob pattern to filter files (e.g., '*.py', '*.txt')", "default": "*"},
            "use_regex": {"type": "boolean", "description": "Treat pattern as regex", "default": False},
            "case_sensitive": {"type": "boolean", "description": "Case sensitive search", "default": False},
            "max_results": {"type": "integer", "description": "Maximum number of matches to return", "default": 50}
        },
        "required": ["pattern"]
    }

    def execute(self, **kwargs) -> Dict[str, Any]:
        pattern = kwargs.get("pattern", "")
        file_pattern = kwargs.get("file_pattern", "*")
        use_regex = kwargs.get("use_regex", False)
        case_sensitive = kwargs.get("case_sensitive", False)
        max_results = kwargs.get("max_results", 50)

        if not pattern:
            return {"success": False, "error": "No search pattern provided"}

        ws = get_workspace()
        if not ws:
            return {"success": False, "error": "No workspace active. Please select a workspace folder first."}

        root = Path(ws)
        if not root.exists():
            return {"success": False, "error": f"Workspace path does not exist: {ws}"}

        # Prepare regex flags
        flags = 0 if case_sensitive else re.IGNORECASE
        if use_regex:
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return {"success": False, "error": f"Invalid regex pattern: {e}"}
        else:
            # Escape regex meta-characters for literal search
            escaped = re.escape(pattern)
            regex = re.compile(escaped, flags)

        matches = []
        # Walk through workspace directory
        for root_dir, dirs, files in os.walk(root):
            # Skip hidden directories (optional)
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for file in files:
                if not fnmatch.fnmatch(file, file_pattern):
                    continue
                file_path = Path(root_dir) / file
                # Skip large files > 5MB to avoid performance issues
                if file_path.stat().st_size > 5 * 1024 * 1024:
                    continue
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()
                    for line_num, line in enumerate(lines, start=1):
                        if regex.search(line):
                            # Generate a snippet (40 chars around match)
                            match_pos = None
                            if use_regex:
                                m = regex.search(line)
                                if m:
                                    match_pos = m.start()
                            else:
                                match_pos = line.lower().find(pattern.lower()) if not case_sensitive else line.find(pattern)
                            if match_pos is not None:
                                start = max(0, match_pos - 40)
                                end = min(len(line), match_pos + 40)
                                snippet = line[start:end].strip()
                            else:
                                snippet = line.strip()[:80]
                            matches.append({
                                "file": str(file_path.relative_to(root)),
                                "line": line_num,
                                "snippet": snippet
                            })
                            if len(matches) >= max_results:
                                break
                except Exception as e:
                    logger.debug(f"Could not read {file_path}: {e}")
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        if not matches:
            return {"success": True, "result": f"No matches found for '{pattern}' in workspace."}

        # Format result
        output = [f"🔍 Found {len(matches)} matches for '{pattern}' in workspace:"]
        for m in matches[:max_results]:
            output.append(f"  📄 {m['file']}:{m['line']} - {m['snippet']}")
        if len(matches) > max_results:
            output.append(f"  ... and {len(matches) - max_results} more.")
        return {"success": True, "result": "\n".join(output)}