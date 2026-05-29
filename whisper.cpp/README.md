# whisper.cpp (Submodule Reference)

LMIM uses whisper.cpp for speech-to-text. The actual source is not included in this repo to keep it small.

## Building from source:
```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
make
```

## Or download pre-built binaries:
- Linux: `voice/bin/whisper-cli`
- Windows: `voice/bin/whisper-cli.exe`

These are downloaded at runtime via `scripts/setup_voice.sh`
