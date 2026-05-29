#!/bin/bash
# Downloads voice binaries at first run (only ~50MB total)

VOICE_DIR="./voice/bin"
mkdir -p "$VOICE_DIR"

echo "📢 Setting up voice components..."

# Whisper-cli (STT) - ~30MB
if [ ! -f "$VOICE_DIR/whisper-cli" ]; then
    echo "  Downloading whisper-cli..."
    wget -q --show-progress -O "$VOICE_DIR/whisper-cli" \
        "https://lmim.tech/static/voice/whisper-cli"
    chmod +x "$VOICE_DIR/whisper-cli"
fi

# Piper (TTS) - ~15MB
if [ ! -f "$VOICE_DIR/piper" ]; then
    echo "  Downloading piper..."
    wget -q --show-progress -O "$VOICE_DIR/piper" \
        "https://lmim.tech/static/voice/piper"
    chmod +x "$VOICE_DIR/piper"
fi

# Piper phonemize library - ~5MB
if [ ! -f "$VOICE_DIR/libpiper_phonemize.so" ]; then
    echo "  Downloading libpiper_phonemize.so..."
    wget -q --show-progress -O "$VOICE_DIR/libpiper_phonemize.so" \
        "https://lmim.tech/static/voice/libpiper_phonemize.so"
fi

# espeak-ng-data (shared voices) - ~30MB
if [ ! -d "voice/espeak-ng-data" ]; then
    echo "  Downloading espeak-ng-data..."
    wget -q --show-progress -O /tmp/espeak-ng-data.tar.gz \
        "https://lmim.tech/static/voice/espeak-ng-data.tar.gz"
    tar -xzf /tmp/espeak-ng-data.tar.gz -C voice/
    rm /tmp/espeak-ng-data.tar.gz
fi

echo "✅ Voice setup complete"
