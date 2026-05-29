#!/usr/bin/env python3
"""
Autonomous multi-file project builder.
Usage: python build_project.py "<prompt>" <user_token>

Prerequisites:
- LMIM engine must be running: python -m app.main (port 5000)
- LM Studio must be running: http://localhost:1234
"""
import sys, requests, time, json, os, re
from pathlib import Path

BASE_URL = os.getenv("GENESYS_API", "http://localhost:5000")
WORKSPACE = Path(os.getenv("GENESYS_WORKSPACE", "/home/ais/lmim_engine/workspace"))
MAX_POLL_ATTEMPTS = 40  # 10 minutes max wait per file (15s intervals)
POLL_INTERVAL = 15  # seconds between status checks
REQUEST_TIMEOUT = 60  # 60 seconds for HTTP requests  # seconds for HTTP requests


def check_server_health() -> bool:
    """Verify LMIM engine is running."""
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def request_build(prompt: str, user_token: str) -> str:
    """Send build request, return task_id or None."""
    try:
        resp = requests.post(
            f"{BASE_URL}/ask",
            data={"prompt": prompt, "userToken": user_token},
            timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        # Extract task_id: "🔨 Build started! Task ID: chat_andres_123..."
        match = re.search(r"Task ID: (chat_\w+_\d+)", resp.text)
        if match:
            return match.group(1)
        print(f"⚠️  Could not parse task_id from: {resp.text[:100]}")
        return None
    except requests.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None


def wait_for_completion(task_id: str, max_attempts: int = MAX_POLL_ATTEMPTS) -> dict:
    """Poll /build/status until success/failure or timeout."""
    for attempt in range(max_attempts):
        try:
            resp = requests.get(f"{BASE_URL}/build/status/{task_id}", timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            
            if status in ["success", "failed"]:
                return data
            elif status == "processing":
                print(f"⏳  {task_id}: processing (attempt {attempt+1}/{max_attempts})...")
                time.sleep(POLL_INTERVAL)
            else:
                print(f"⚠️  {task_id}: unknown status '{status}', waiting...")
                time.sleep(POLL_INTERVAL)
        except requests.ConnectionError:
            print(f"❌ Server connection lost. Is app.main running on {BASE_URL}?")
            return {"status": "error", "error": "Server unreachable"}
        except requests.RequestException as e:
            print(f"⚠️  Poll error: {e}, retrying...")
            time.sleep(POLL_INTERVAL)
    
    print(f"❌ {task_id}: timeout after {max_attempts} polls")
    return {"status": "timeout", "task_id": task_id}


def parse_project_files(prompt: str) -> list[str]:
    """Extract target filenames from natural language prompt."""
    files = ["solution.py"]
    p = prompt.lower()
    if any(k in p for k in ["test", "pytest", "unit test", "testing"]):
        files.append("test_solution.py")
    if any(k in p for k in ["requirements", "dependencies", "pip install", "packages"]):
        files.append("requirements.txt")
    if "readme" in p or "documentation" in p or "docs" in p:
        files.append("README.md")
    return files


def build_file(project_prompt: str, user_token: str, filename: str) -> dict:
    """Request single file generation and wait for completion."""
    # Tailor prompt for specific file type
    if filename == "test_solution.py":
        file_prompt = f"""{project_prompt}

🎯 TASK: Generate pytest tests ONLY — DO NOT store memory, DO NOT output JSON, DO NOT mention project structure.

🚫 ABSOLUTE PROHIBITIONS:
1. NO [TOOL_CALL] markers, NO JSON tool syntax, NO store_memory/recall_memory calls
2. NO markdown fences (```), NO explanations, NO comments about the task
3. If you start to output a tool call, STOP and output test code instead

OUTPUT RULES (STRICT):
1. Output ONLY raw Python test code
2. Assume the main module (solution.py) exists: `from solution import *`
3. Use hardcoded test values only (never function parameters in assertions)
4. Include at least 3 test functions: test_add, test_list, test_delete
5. Start with: `import pytest` then `def test_...`

BEGIN TEST CODE NOW (raw Python only):"""
    elif filename == "requirements.txt":
        file_prompt = f"{project_prompt}\n\nOUTPUT INSTRUCTIONS:\n- Write ONLY a requirements.txt file\n- List only essential Python packages with versions\n- One package per line, no comments, no markdown\n- Output raw text only"
    elif filename == "README.md":
        file_prompt = f"{project_prompt}\n\nOUTPUT INSTRUCTIONS:\n- Write ONLY a README.md file\n- Use markdown format\n- Include: project title, description, usage example, installation\n- Output raw markdown only, no code fences around the whole doc"
    else:  # solution.py or default
        file_prompt = f"{project_prompt}\n\nOUTPUT INSTRUCTIONS:\n- Save as {filename}\n- Output ONLY raw code, no markdown fences, no explanations\n- Include necessary imports at the top\n- If the task mentions testing, include a simple __main__ test block with hardcoded values"
    
    print(f"🔨 Requesting {filename}...")
    task_id = request_build(file_prompt, user_token)
    if not task_id:
        return {"status": "error", "filename": filename, "error": "Failed to submit build request"}
    
    print(f"⏳  Waiting for {filename} (task: {task_id})...")
    result = wait_for_completion(task_id)
    
    if result.get("status") == "success":
        # Optionally rename output file if not default
        if filename != "solution.py":
            src = WORKSPACE / "solution.py"
            dst = WORKSPACE / filename
            if src.exists() and not dst.exists():
                src.rename(dst)
                print(f"📝 Saved as {filename}")
        return {"status": "success", "filename": filename, "task_id": task_id, **result}
    else:
        return {"status": result.get("status", "unknown"), "filename": filename, "task_id": task_id, **result}


def main():
    if len(sys.argv) < 3:
        print("Usage: python build_project.py '<project prompt>' <user_token>")
        print("Example: python build_project.py 'Create a CLI todo app with tests' andres")
        print("\n⚠️  Prerequisites:")
        print("   1. LMIM engine running: python -m app.main (port 5000)")
        print("   2. LM Studio running: http://localhost:1234")
        sys.exit(1)
    
    # Check server health first
    if not check_server_health():
        print(f"❌ LMIM engine not responding at {BASE_URL}")
        print("   Please start it first: cd ~/lmim_engine && poetry run python -m app.main")
        sys.exit(2)
    print(f"✅ Connected to LMIM engine at {BASE_URL}")
    
    project_prompt = sys.argv[1]
    user_token = sys.argv[2]
    
    print(f"🗂️  Building project: {project_prompt[:70]}...")
    target_files = parse_project_files(project_prompt)
    print(f"📋 Target files: {target_files}")
    
    results = {}
    history_path = WORKSPACE / "project_history.json"
    
    # Load existing history for crash-resume
    existing_results = {}
    if history_path.exists():
        try:
            with open(history_path, 'r') as f:
                all_history = json.load(f)
                for entry in reversed(all_history[-20:]):
                    if entry.get("prompt") == project_prompt and entry.get("user") == user_token:
                        existing_results = entry.get("results", {})
                        if existing_results:
                            print(f"🔄 Resuming: {len(existing_results)} files from previous run")
                        break
        except Exception as e:
            print(f"⚠️  Could not load history: {e}")
    
    for filename in target_files:
        # Skip if already successful
        if filename in existing_results and existing_results[filename].get("status") == "success":
            print(f"⏭️  Skipping {filename} (already successful)")
            results[filename] = existing_results[filename]
            continue
        
        result = build_file(project_prompt, user_token, filename)  # ✅ Correct 3 args
        results[filename] = result
        symbol = "✅" if result.get("status") == "success" else "❌"
        print(f"{symbol} {filename}: {result.get('status')}")
        
        # Save progress after each file (crash-resume)
        history_entry = {
            "timestamp": time.time(),
            "prompt": project_prompt,
            "user": user_token,
            "results": results
        }
        all_history = []
        if history_path.exists():
            try:
                with open(history_path, 'r') as f:
                    all_history = json.load(f)
            except:
                pass
        all_history.append(history_entry)
        with open(history_path, 'w') as f:
            json.dump(all_history[-50:], f, indent=2)
    
    # Final summary
    print(f"\n{'='*60}")
    print("📊 Build Summary:")
    success_count = sum(1 for r in results.values() if r.get("status") == "success")
    for fname, res in results.items():
        status = res.get("status", "unknown")
        symbol = "✅" if status == "success" else "❌"
        attempts = res.get("attempts", "?")
        print(f"  {symbol} {fname:25} → {status:10} (attempts: {attempts})")
    
    print(f"\n🎯 Overall: {success_count}/{len(results)} files succeeded")
    if success_count == len(results):
        print("🎉 Project build complete!")
    elif success_count > 0:
        print("⚠️  Partial success — re-run to retry failed files")
    else:
        print("❌ All files failed — check logs for details")
    
    print(f"💾 History saved to {history_path}")
    sys.exit(0 if success_count == len(results) else 1)


if __name__ == "__main__":
    main()
