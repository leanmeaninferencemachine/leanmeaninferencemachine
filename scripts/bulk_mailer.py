#!/usr/bin/env python3
"""
Bulk Email Sender for DreamHost SMTP (Enhanced with Resume & Logging)
Usage: python3 scripts/bulk_mailer.py --subject="Welcome Back!" --template="Hi {name}..."
"""
import smtplib
import csv
import time
import argparse
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.dreamhost.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = SMTP_USER
FROM_NAME = os.getenv("SMTP_FROM_NAME", "LMIM Education")

LOG_FILE = "data/sent_log.csv"

def send_bulk_email(subject, body_template, csv_path="data/ex_clients.csv", delay=2, use_html=False):
    if not SMTP_USER or not SMTP_PASS:
        print("❌ Error: SMTP credentials not found in .env")
        return

    # Load already sent emails to resume safely
    sent_emails = set()
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            sent_emails = {row['email'] for row in reader if row['status'] == 'success'}
        print(f"📋 Resuming: {len(sent_emails)} emails already marked as sent.")

    print(f"📧 Connecting to {SMTP_SERVER}:{SMTP_PORT}...")
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        print("✅ Connected successfully.")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return

    if not os.path.exists(csv_path):
        print(f"❌ File not found: {csv_path}")
        server.quit()
        return

    with open(csv_path, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        recipients = list(reader)

    total_recipients = len(recipients)
    print(f"📋 Total recipients: {total_recipients}")
    print(f"🚀 Starting blast (skipping {len(sent_emails)} already sent)...")
    
    success_count = len(sent_emails)
    fail_count = 0
    
    # Ensure log file exists with headers
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode='a', newline='', encoding='utf-8') as log_f:
        fieldnames = ['email', 'name', 'status', 'timestamp', 'error']
        writer = csv.DictWriter(log_f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for i, row in enumerate(recipients):
            recipient_email = row.get('email')
            recipient_name = row.get('name', 'Friend')
            
            if not recipient_email:
                continue
            
            # Skip if already sent (Resume Logic)
            if recipient_email in sent_emails:
                continue

            # Personalize body
            final_body = body_template.replace("{name}", recipient_name)
            
            msg = MIMEMultipart()
            msg['From'] = f"{FROM_NAME} <{FROM_EMAIL}>"
            msg['To'] = recipient_email
            msg['Subject'] = subject
            
            # Attach as HTML or Plain Text
            mime_type = 'html' if use_html else 'plain'
            msg.attach(MIMEText(final_body, mime_type))

            try:
                server.send_message(msg)
                print(f"   ✅ [{success_count+1}/{total_recipients}] Sent to {recipient_email} ({recipient_name})")
                
                # Log Success
                writer.writerow({
                    'email': recipient_email,
                    'name': recipient_name,
                    'status': 'success',
                    'timestamp': datetime.now().isoformat(),
                    'error': ''
                })
                log_f.flush() # Ensure written immediately
                success_count += 1
                sent_emails.add(recipient_email)
                
            except Exception as e:
                err_msg = str(e)
                print(f"   ❌ [{success_count+1}/{total_recipients}] Failed {recipient_email}: {err_msg}")
                
                # Log Failure
                writer.writerow({
                    'email': recipient_email,
                    'name': recipient_name,
                    'status': 'failed',
                    'timestamp': datetime.now().isoformat(),
                    'error': err_msg
                })
                log_f.flush()
                fail_count += 1
            
            # Throttle
            if i < len(recipients) - 1:
                time.sleep(delay)

    server.quit()
    print("-" * 40)
    print(f"🎉 Session Complete! Total Success: {success_count}, New Failures: {fail_count}")
    print(f"📄 Detailed log saved to: {LOG_FILE}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send bulk emails via DreamHost SMTP")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--template", required=True, help="Email body (use {name} for personalization)")
    parser.add_argument("--file", default="data/ex_clients.csv", help="Path to CSV file")
    parser.add_argument("--delay", type=int, default=2, help="Seconds between emails")
    parser.add_argument("--html", action="store_true", help="Send as HTML instead of plain text")
    
    args = parser.parse_args()
    
    send_bulk_email(args.subject, args.template, args.file, args.delay, args.html)