#!/usr/bin/env python3
"""
Bulk WhatsApp Sender - SAFE ATTEMPT LOGIC.
FIX: Marks ANY navigation attempt as 'success_attempted' to prevent retries.
Only 'success' counts as verified sent. 'success_attempted' means we tried but didn't verify.
"""
import asyncio
import csv
import os
import random
import argparse
import urllib.parse
import shutil
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

LOG_FILE = "data/whatsapp_sent_log.csv"
BULK_PROFILE_DIR = Path("data/chrome_profile_bulk").resolve()

def normalize_phone(phone: str) -> str:
    """Strips all non-digits to ensure consistent comparison."""
    if not phone: return ""
    return ''.join(filter(str.isdigit, str(phone)))

def get_chrome_path():
    paths = ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]
    for path in paths:
        if shutil.which(path):
            return path
    return None

SYSTEM_CHROME = get_chrome_path()
if not SYSTEM_CHROME:
    print("❌ CRITICAL: Chrome/Chromium not found.")
    exit(1)

async def send_bulk_whatsapp(message_template, csv_path, headless=True, max_batch=50):
    if not message_template or not message_template.strip():
        print("❌ Error: Message template is empty!")
        return
    if not os.path.exists(csv_path):
        print(f"❌ File not found: {csv_path}")
        return

    # === 🔴 ROBUST LOG LOADING (Normalized) ===
    sent_phones = set()
    skipped_phones = set()
    
    if os.path.exists(LOG_FILE):
        print("📊 Analyzing log file for definitive status...")
        all_entries = []
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            all_entries = list(reader)
        
        # Pass 1: Identify ALL phones with ANY attempt (success OR success_attempted)
        for row in all_entries:
            clean_p = normalize_phone(row['phone'])
            status = row['status']
            # If it was sent OR attempted, we NEVER retry
            if status in ['success', 'success_attempted']:
                sent_phones.add(clean_p)
        
        # Pass 2: Identify skipped phones (only if they NEVER succeeded/attempted)
        for row in all_entries:
            clean_p = normalize_phone(row['phone'])
            if clean_p not in sent_phones and row['status'] == 'skipped_permanent':
                skipped_phones.add(clean_p)
        
        print(f"✅ Definitive Status: {len(sent_phones)} Processed (Sent/Attempted), {len(skipped_phones)} Skipped.")
    else:
        print("📋 No log file found. Starting fresh.")

    # Load Contacts
    with open(csv_path, 'r', encoding='utf-8') as f:
        contacts = list(csv.DictReader(f))

    print(f"📋 Total contacts in CSV: {len(contacts)}")
    
    # === 🛑 DRY RUN: Determine exactly who will be messaged ===
    to_send_list = []
    for contact in contacts:
        raw_phone = contact.get('phone')
        clean_phone = normalize_phone(raw_phone)
        
        if not clean_phone: continue
        if clean_phone in sent_phones:
            continue 
        if clean_phone in skipped_phones: 
            continue
        
        to_send_list.append((contact, clean_phone))
    
    print(f"🎯 PLAN: Found {len(to_send_list)} pending contacts.")
    if len(to_send_list) == 0:
        print("✅ All contacts already processed. Exiting.")
        return
    
    print(f"🚀 Will send to first {min(max_batch, len(to_send_list))} pending contacts:")
    for i, (contact, clean_p) in enumerate(to_send_list[:5]):
        print(f"   {i+1}. {contact.get('name')} ({clean_p})")
    if len(to_send_list) > 5:
        print(f"   ... and {len(to_send_list) - 5} more.")
    
    print(f"🚀 Starting Bulk Sender (Chrome: {SYSTEM_CHROME})...")
    print(f"📂 Profile Dir: {BULK_PROFILE_DIR}")

    BULK_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(BULK_PROFILE_DIR),
                executable_path=SYSTEM_CHROME,
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1920,1080"],
                viewport={"width": 1920, "height": 1080}
            )
        except Exception as e:
            print(f"❌ Failed to launch browser: {e}")
            return

        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

        print("🌐 Loading WhatsApp Web...")
        await page.goto("https://web.whatsapp.com")
        
        print("⏳ Waiting for login...")
        try:
            loaded = False
            wait_time = 0
            while wait_time < 90:
                if await page.is_visible('#pane-side'):
                    print("✅ Main interface loaded.")
                    loaded = True
                    break
                
                if await page.is_visible('canvas[data-icon="qr-code"]'):
                    if headless:
                        print("❌ ERROR: QR detected in HEADLESS mode. Run with --window to scan.")
                        loaded = False
                        break
                    print("📱 QR Code detected. Waiting for scan...")
                    try:
                        await page.wait_for_selector('canvas[data-icon="qr-code"]', state='hidden', timeout=300000)
                        print("✅ Scanned! Session saved.")
                        await asyncio.sleep(2)
                        await page.wait_for_selector('#pane-side', timeout=30000)
                        loaded = True
                        break
                    except Exception as scan_err:
                        print(f"❌ Scan timed out: {scan_err}")
                        break

                if await page.is_visible('label:has-text("Keep me signed in")'):
                    await page.click('label:has-text("Keep me signed in")')
                    await asyncio.sleep(1)
                
                await asyncio.sleep(2)
                wait_time += 2
                if wait_time % 10 == 0: print(f"   ...waiting ({wait_time}s)")

            if not loaded:
                await context.close()
                return
            print("✅ WhatsApp Loaded Successfully!")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"❌ Login failed: {e}")
            await context.close()
            return

        success_count = 0
        attempt_count = 0
        skip_count = 0
        batch_count = 0
        browser_crashed = False

        file_exists = os.path.isfile(LOG_FILE)
        with open(LOG_FILE, 'a', newline='', encoding='utf-8') as log_f:
            fieldnames = ['phone', 'name', 'status', 'error']
            writer = csv.DictWriter(log_f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()

            for i, (contact, clean_phone) in enumerate(to_send_list):
                name = contact.get('name', 'Friend')
                raw_phone = contact.get('phone')

                if batch_count >= max_batch:
                    print(f"\n⚠️  Batch limit ({max_batch}) reached. Stopping.")
                    break

                # 🔧 HEARTBEAT CHECK
                try:
                    await asyncio.sleep(1) 
                    if await page.is_visible('canvas[data-icon="qr-code"]'):
                        print("\n🚨 CRITICAL: QR Code Reappeared! Session lost.")
                        browser_crashed = True
                        break
                    if await page.is_visible('div[data-testid="fallback-app"]'):
                        print("\n🚨 CRITICAL: Fallback App Error.")
                        browser_crashed = True
                        break
                except Exception:
                    pass

                msg_body = message_template.replace("{name}", name)
                url = f"https://web.whatsapp.com/send?phone={clean_phone}&text={urllib.parse.quote(msg_body)}"
                
                print(f"   📤 [{batch_count+1}] Sending to {name} ({clean_phone})...")
                
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    
                    input_selector = 'div[contenteditable="true"][data-tab="10"]'
                    chat_header = 'div[data-testid="conversation-info-header-chat-title"]'
                    
                    # Wait for UI to resolve
                    try:
                        await page.wait_for_selector(f"{input_selector}, {chat_header}", timeout=15000)
                    except PlaywrightTimeout:
                        # ⚠️ CHANGE: Instead of 'failed', mark as 'success_attempted'
                        print("      ⚠️  Timeout waiting for chat. Marking as ATTEMPTED (Won't retry).")
                        writer.writerow({'phone': raw_phone, 'name': name, 'status': 'success_attempted', 'error': 'Nav Timeout - Unverified'})
                        log_f.flush()
                        attempt_count += 1
                        batch_count += 1
                        continue

                    # 🚨 AGGRESSIVE SKIP CHECKS
                    is_invalid = False
                    error_reason = "Unknown"

                    if await page.is_visible('span[data-icon="alert-circle"]'):
                        is_invalid = True
                        error_reason = "Invalid Number (Alert Icon)"
                    
                    try:
                        await page.wait_for_selector(input_selector, state="visible", timeout=5000)
                    except PlaywrightTimeout:
                        is_invalid = True
                        error_reason = "No Input Box (Not on WhatsApp?)"

                    if is_invalid:
                        print(f"      ⚠️  {error_reason}. Marking SKIPPED PERMANENTLY.")
                        writer.writerow({'phone': raw_phone, 'name': name, 'status': 'skipped_permanent', 'error': error_reason})
                        log_f.flush()
                        skip_count += 1
                        batch_count += 1 # Counts towards batch limit
                        continue

                    # ✅ Valid Chat Found - Send
                    await page.focus(input_selector)
                    await asyncio.sleep(1)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(2)
                    
                    writer.writerow({'phone': raw_phone, 'name': name, 'status': 'success', 'error': ''})
                    log_f.flush()
                    success_count += 1
                    batch_count += 1
                    print("      ✅ Sent & Verified!")

                except Exception as e:
                    err_msg = str(e)
                    # ⚠️ CHANGE: Any other exception is also an 'attempt'
                    print(f"      ❌ Failed: {err_msg}. Marking as ATTEMPTED (Won't retry).")
                    writer.writerow({'phone': raw_phone, 'name': name, 'status': 'success_attempted', 'error': f'Exception: {err_msg}'})
                    log_f.flush()
                    attempt_count += 1
                    batch_count += 1

                delay = random.uniform(15, 25)
                print(f"      ⏳ Waiting {delay:.1f}s...")
                await asyncio.sleep(delay)

        await context.close()
        
        if browser_crashed:
            print("\n" + "="*50)
            print("🛑 STOPPED DUE TO CRASH.")
            print("="*50)
        else:
            print("-" * 40)
            print(f"🎉 Complete!")
            print(f"   ✅ Verified Sent: {success_count}")
            print(f"   ⚠️  Attempted (Unverified): {attempt_count}")
            print(f"   ⏭️  Skipped (Invalid): {skip_count}")
            print(f"   📝 Total Processed: {success_count + attempt_count + skip_count}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk WhatsApp Sender")
    parser.add_argument("--message", required=True, help="Message template")
    parser.add_argument("--file", default="data/whatsapp_contacts.csv", help="CSV file")
    parser.add_argument("--batch", type=int, default=50, help="Max messages per run")
    parser.add_argument("--window", action="store_true", help="Show browser window")
    
    args = parser.parse_args()
    asyncio.run(send_bulk_whatsapp(args.message, args.file, headless=not args.window, max_batch=args.batch))
