# Voice Binaries

This directory holds speech-to-text (whisper) and text-to-speech (piper) binaries.

## Directory Structure

```
voice/
├── bin/                    # Binaries (downloaded at runtime)
│   ├── whisper-cli         # STT binary
│   ├── piper               # TTS binary
│   └── lib*.so             # Shared libraries
├── espeak-ng-data/         # eSpeak-NG phoneme data
└── models/
    ├── stt/                # Whisper models (downloaded automatically)
    └── tts/                # Piper voice files (.onnx)
```

## Setup

Run the setup script to download binaries:
- Linux: `bash scripts/setup_voice.sh`
- Windows: `.\scripts\setup_voice.ps1`

## Manual Download

If scripts fail, download from:
- https://lmim.tech/static/voice/whisper-cli
- https://lmim.tech/static/voice/piper
- https://lmim.tech/static/voice/espeak-ng-data.tar.gz

## Notes

- Binaries are platform-specific (Linux ELF vs Windows PE)
- Whisper models download automatically on first use
- TTS voice files are separate downloads
