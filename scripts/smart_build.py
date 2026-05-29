#!/usr/bin/env python3
"""
Smart Build: Ask LMIM to read, plan, and build a file, then watch progress.
Usage: python3 scripts/smart_build.py "Your prompt here" [user_id]
"""
import sys
import requests
import time
import json

BASE_URL = "http://localhost:5000"

def main():
    if len(sys.argv) < 2:
        print("❌ Usage: python3 scripts/smart_build.py \"<prompt>\" [user_id]")
        sys.exit(1)

    prompt = sys.argv[1]
    user_id = sys.argv[2] if len(sys.argv) > 2 else "andres"

    print(f"🚀 LMIM Smart Build")
    print(f"🗣️  Prompt: {prompt}")
    print(f"👤 User: {user_id}")
    print("-" * 50)

    # 1. Trigger the Auto-Build Pipeline (Plan + Queue)
    print("📡 Sending request to /build/auto (Planning & Queuing)...")
    try:
        resp = requests.post(f"{BASE_URL}/build/auto", data={
            "prompt": prompt,
            "userToken": user_id
        }, timeout=8000)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"❌ Failed to start build: {e}")
        sys.exit(1)

    if data.get("status") != "building":
        print(f"❌ Build failed to start: {data}")
        sys.exit(1)

    manifest = data.get("manifest", {})
    tasks = data.get("tasks", [])
    
    print(f"✅ Plan Generated: {manifest.get('project_name')}")
    print(f"📋 Files to build: {', '.join(manifest.get('build_order', []))}")
    print(f"🔨 Tasks queued: {len(tasks)}")
    print("-" * 50)

    # 2. Poll each task until complete
    all_success = True
    for task_id in tasks:
        # Extract filename from task_id (format: auto_user_filename_time)
        parts = task_id.split('_')
        filename = parts[2] if len(parts) > 2 else "unknown"
        
        print(f"\n🔨 Building: {filename}...")
        attempt = 0
        while True:
            try:
                status_resp = requests.get(f"{BASE_URL}/build/status/{task_id}", timeout=90)
                status_data = status_resp.json()
                status = status_data.get("status", "unknown")
            except:
                status = "connection_error"

            if status == "success":
                print(f"   ✅ {filename}: SUCCESS (Attempts: {status_data.get('attempts', 1)})")
                break
            elif status == "failed":
                print(f"   ❌ {filename}: FAILED")
                print(f"      Error: {status_data.get('error', 'Unknown')}")
                all_success = False
                break
            else:
                # Show activity
                sys.stdout.write(".")
                sys.stdout.flush()
                time.sleep(2)
                attempt += 1
                if attempt > 4000: # 2 min timeout per file
                    print(f"\n   ⚠️ {filename}: Timeout waiting for response")
                    all_success = False
                    break
    
    print("\n" + "=" * 50)
    if all_success:
        print("🎉 BUILD COMPLETE! All files generated successfully.")
        print(f"💾 Check your workspace: ls -la workspace/")
    else:
        print("⚠️ Build finished with errors. Check logs for details.")
    
    sys.exit(0 if all_success else 1)

if __name__ == "__main__":
    main()
