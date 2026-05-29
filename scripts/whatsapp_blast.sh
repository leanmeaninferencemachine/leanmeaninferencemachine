#!/bin/bash
# WhatsApp Auto-Cycle: Reads message from file, sends batch, waits, repeats.

# Define paths relative to the project root (genesys_engine)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MESSAGE_FILE="$PROJECT_ROOT/data/wa_message.txt"
CONTACTS_FILE="$PROJECT_ROOT/data/whatsapp_contacts.csv"

BATCH_SIZE=30
WAIT_HOURS=2

echo "🚀 Starting WhatsApp Auto-Cycle..."
echo "   📂 Project Root: $PROJECT_ROOT"
echo "   📄 Message File: $MESSAGE_FILE"
echo "   📦 Batch Size: $BATCH_SIZE"
echo "   ⏳ Wait Time: $WAIT_HOURS hours"

# Check if message file exists
if [ ! -f "$MESSAGE_FILE" ]; then
    echo "❌ ERROR: Message file not found at $MESSAGE_FILE"
    exit 1
fi

# Read the message content (handles spaces and special chars)
MESSAGE_CONTENT=$(cat "$MESSAGE_FILE")

if [ -z "$MESSAGE_CONTENT" ]; then
    echo "❌ ERROR: Message file is empty!"
    exit 1
fi

echo "   📝 Message Preview: ${MESSAGE_CONTENT:0:50}..."

while true; do
    echo "----------------------------------------"
    echo "🕒 [$(date)] Starting batch of $BATCH_SIZE..."
    
    # Run the python script with the EXACT content from the file
    cd "$PROJECT_ROOT"
    python3 scripts/bulk_whatsapp.py \
      --message="$MESSAGE_CONTENT" \
      --file="$CONTACTS_FILE" \
      --batch=$BATCH_SIZE \
      --window
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -ne 0 ]; then
        echo "❌ Script failed or stopped unexpectedly (Exit Code: $EXIT_CODE). Exiting loop."
        exit $EXIT_CODE
    fi
    
    echo "✅ Batch complete!"
    echo "⏳ Sleeping for $WAIT_HOURS hours... (Press Ctrl+C to stop)"
    sleep $((WAIT_HOURS * 3600))
done
