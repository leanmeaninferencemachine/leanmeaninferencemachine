# ⚡ LMIM OS v2 "Tezcat" — Lean Mean Inference Machine

> **Codename: Tezcat** — Named after Tezcatlipoca, the Aztec god of sorcery, night, and mirrors. Built through fire. GPU-powered magic.

**Local-first AI operating system. No cloud. No subscription. No API fees.**

LMIM OS bundles a full AI assistant with local LLM inference, voice, scheduling,
multi-channel messaging, and developer tools — all running on your hardware.

---

## 🆕 What's New in v2

### ⚡ GPU Acceleration (CUDA)
- **llama.cpp** — 3-15x faster LLM inference with CUDA offloading
- **whisper.cpp** — GPU-accelerated speech-to-text (STT)
- Automatic GPU detection. Falls back to CPU if no CUDA available.
- **Supported GPUs:** NVIDIA GTX 10xx+ / RTX 20xx+ / RTX 30xx+ / RTX 40xx+ (compute capability 7.5+)
- **Requires:** NVIDIA driver 535+ (CUDA 12.2+) for Maxwell/Pascal. Driver 545+ for best compatibility.
- AppImage ships with PTX for compute capabilities: 75, 86, 89
- If you have an older GPU (6.1 Pascal): build from source with `-DCMAKE_CUDA_ARCHITECTURES=61`

### 🎤 Voice Engine
- **Voice tab** — microphone selection, speaker output routing
- **STT** — Click-to-record orb in chat. Language toggle (EN/ES). Auto-transcribes and sends.
- **TTS** — AI replies spoken aloud via Piper. 5 languages: English, Spanish, Portuguese, French, German.
- **Auto-speak** — Only new AI replies are spoken. Toggle on/off.

### 🧰 Developer Toolbox
- **File Hash Checker** — SHA-1, SHA-256, SHA-384, SHA-512 + comparison mode
- **CSS Minifier** — Strip comments, collapse whitespace, size stats
- **JS Minifier** — Strip comments, collapse whitespace, size stats
- **JSON Validator/Formatter** — Pretty-print or minify. Instant validation.

### 📱 WhatsApp Integration
- **QR pairing** — Scan directly in dashboard. Auto-reconnects.
- **Campaign Blaster** — Bulk messaging via WhatsApp or Email with CSV lists.
- **Service Switch** — Start/stop all daemons from GUI with live status.

### 🎛️ Full-Featured Dashboard
- Multi-chat with persistent history
- Visual agenda (FullCalendar) with auto-refresh
- Setup wizard + onboarding tour
- Local/Cloud AI toggle
- System diagnostics (CPU, RAM, disk, uptime)
- Update notifications with one-click download

---

## 📦 Installation

### Prerequisites
- **Linux** (Ubuntu 22.04+ recommended, Fedora 40+ supported)
- **Python 3.10+** with pip
- **Node.js 18+** (for WhatsApp daemon)
- **CUDA Toolkit 12.x** + **NVIDIA driver 545+** (optional — for GPU acceleration)

### Quick Start
```bash
# Download the AppImage
chmod +x LMIM_OS_*.AppImage
./LMIM_OS_*.AppImage
```

### From Source
```bash
git clone https://github.com/leanmeaninferencemachine/leanmeaninferencemachine
cd leanmeaninferencemachine

# Setup Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup Node (for WhatsApp)
npm install

# Build llama.cpp with CUDA (optional)
cd llama.cpp
mkdir build && cd build
cmake .. -DGGML_CUDA=ON && cmake --build . -j$(nproc)

# Build whisper.cpp with CUDA (optional)
cd ../../whisper.cpp
mkdir build && cd build
cmake .. -DGGML_CUDA=ON && cmake --build . -j$(nproc)

# Launch
cd ../..
python3 run_app_backend.py
```

### First Launch
1. Complete the Setup Wizard (name, AI assistant name, tone)
2. Accept the safety disclaimer
3. Take the onboarding tour (or skip — relaunch anytime)
4. Select your model in Settings → Local AI Configuration
5. For GPU: ensure CUDA is installed, then toggle Local mode and save

---

## 🧠 Features

### AI Assistant with Agents
- **Planner Agent** — Takes a vague request ("Build me a dashboard") and turns it into a structured spec
- **Builder Agent** — Writes, tests, and iterates code autonomously. Handles syntax errors internally.
- **Inspector Agent** — Validates generated code against requirements before deployment
- **WhatsApp Agent** — Understands WhatsApp users, handles profile context, sends confirmations
- Tool calling: web search, memory, scheduling, messaging, file operations
- All agents route through a unified intent router — no complex configuration needed

### Multi-Channel Communication
- **WhatsApp** — Baileys web protocol (protocol-level, not Selenium). QR pairing in dashboard. Auto-reply. Auto-reconnect on session expiry. Bulk campaigns.
- **Telegram** — Bot API with polling/webhook modes. Inbound auto-reply.
- **Email** — SMTP/IMAP daemon. Processes incoming emails. Bulk campaigns with CSV contacts.
- **Slack** — Bot token integration. Inbound webhooks. Auto-reply.
- **Discord** — Bot token. Inbound messages processed through the AI.
- All daemons manageable from the **Service Switch** page — start/stop with live status

### Meeting Scheduling & Calendar
- FullCalendar visual agenda with auto-refresh
- Book meetings via natural language: *"Schedule Pedro tomorrow at 3pm for English class"*
- AI checks availability, books the slot, updates the calendar
- **WhatsApp confirmation sent automatically** to the person booked — they get a message with date, time, and meeting type
- Tenant support for multi-organization deployments
- All agenda data stored locally as JSON — no cloud calendar sync needed

### Voice Engine
- **Whisper.cpp STT** — GPU-accelerated with CUDA. 3-second transcription. EN + ES.
- **Piper TTS** — 5 languages (EN, ES, PT, FR, DE). AI replies spoken aloud.
- Click-to-record voice orb in chat. Auto-transcribes and auto-sends.
- Microphone/speaker device selection
- Language toggle pill (EN/ES) in the chat bar

### Local AI Runtime
- llama.cpp with CUDA acceleration — 3-15x faster on NVIDIA GPUs
- Qwen 3.5 models bundled (0.8B for speed, 2B for reliability, 4B for quality)
- Automatic GPU detection. Falls back to CPU seamlessly.
- Optional cloud fallback: OpenAI, Anthropic, Groq (toggle in Settings)
- Persistent memory per user — the AI remembers preferences across sessions

### Developer Tools
- File hash checker (SHA-1/256/384/512 + comparison)
- CSS/JS minifier with size statistics
- JSON validator/formatter/minifier

### System
- Real-time diagnostics (CPU, RAM, disk I/O, uptime)
- Version checker with update notifications and one-click download
- Dark theme UI with onboarding tour
---
## ⚡ What Makes LMIM Different

| Other Local AI Tools | LMIM OS |
|----------------------|---------|
| Chat only | **Chat + agents + daemons + calendar + voice + toolbox** |
| You copy-paste code | **Builder agent writes, tests, and iterates code autonomously** |
| Manual scheduling | **"Schedule Pedro at 3pm" → calendar updated + WhatsApp sent** |
| Single model | **Planner → Builder → Inspector chain. Multi-agent pipeline.** |
| Web UI only | **Electron desktop app + AppImage. Zero terminal needed.** |
| Cloud-dependent voice | **Whisper + Piper fully on-device. No audio leaves your machine.** |
| Separate tools | **One dashboard. All communication daemons in one place.** |


## 🏗️ Architecture

```
LMIM OS
├── llama.cpp/          — LLM inference engine (GPU via CUDA)
├── whisper.cpp/        — Speech-to-text (GPU via CUDA)
├── voice/
│   ├── bin/            — piper (TTS), whisper-cli (STT)
│   └── models/
│       ├── stt/        — ggml-small.bin (Whisper model)
│       └── tts/        — en_US-*.onnx, es_MX-*.onnx (Piper voices)
├── app/
│   ├── main.py         — Flask server
│   ├── router.py       — Intent routing (chat, build, WhatsApp)
│   ├── model_interface.py — LLM API wrapper
│   ├── voice_service.py   — STT/TTS service
│   └── tools/          — Web search, scheduling, memory, file ops
├── daemons/            — WhatsApp, Telegram, Email, Slack, Discord
├── electron/           — Desktop wrapper (Electron)
├── templates/          — Dashboard HTML
└── data/               — User config, memories, logs, agendas
```

---

## 🔧 Runtime Dependencies

### GPU Acceleration
- **CUDA Toolkit 12.x** (tested with 12.6)
- **NVIDIA drivers**
  - **535+** (CUDA 12.2) — Minimum for Maxwell/Pascal (GTX 9xx/10xx)
  - **545+** (CUDA 12.4+) — Recommended for Turing/Ampere/Ada (GTX 16xx, RTX 20xx+)
  - **550+** (CUDA 12.5+) — Required for full Blackwell support (RTX 50xx)
- Required libraries: `libcudart.so.12`, `libcublas.so.12`, `libcublasLt.so.12`
- Expected CUDA path: `/usr/local/cuda-12.6/lib64/` or `/usr/local/cuda/lib64/`
- **GPU Compute Capabilities bundled in AppImage:** 7.5 (Turing), 8.6 (Ampere), 8.9 (Ada Lovelace)
- **Older GPUs (Pascal 6.1, Maxwell 5.2):** Must build from source. See GitHub README.

### Voice (STT/TTS)
- **ffmpeg** — Audio conversion (WebM → WAV)
- **Piper** — Bundled at `voice/bin/piper`
- **Whisper.cpp** — Bundled at `voice/bin/whisper-cli`
- TTS models: `voice/models/tts/*.onnx`
- STT models: `voice/models/stt/ggml-*.bin`

### Daemons
- **Node.js 18+** — WhatsApp Baileys daemon
- **Playwright** — WhatsApp Web automation
- npm: `@whiskeysockets/baileys`, `@hapi/boom`, `qrcode`

---

## 📁 Data Locations

| Purpose | Path |
|---------|------|
| User config | `~/.lmim_os/.env` |
| Identity | `~/.lmim_os/config/user_identity.json` |
| Memories | `~/.lmim_os/memories/` |
| Logs | `~/.lmim_os/logs/` |
| WhatsApp auth | `~/.lmim_os/whatsapp/auth/` |
| Sent log | `~/.lmim_os/data/sent_log.csv` |

---

## 🚀 Performance

| Task | CPU (i7-12700H) | GPU (GTX 1650 Ti, 4GB) | GPU (RTX 3060, 12GB) |
|------|-----------------|------------------------|------------------------|
| LLM prompt processing | ~50 tok/s | ~900 tok/s | ~2500 tok/s |
| LLM token generation (2B) | ~5 tok/s | ~80 tok/s | ~120 tok/s |
| LLM token generation (0.8B) | ~10 tok/s | ~85 tok/s | ~150 tok/s |
| Whisper STT (small, 5s audio) | ~7s | ~0.5s | ~0.3s |
| Piper TTS | <1s | <1s | <1s |

*Tested on: Qwen3.5 models, ggml-small.bin Whisper model*
*GPU performance varies by VRAM, compute capability, and driver version.*

---

## 🔗 Links

- **Website:** [https://lmim.tech](https://lmim.tech)
- **GitHub:** [https://github.com/leanmeaninferencemachine/leanmeaninferencemachine](https://github.com/leanmeaninferencemachine/leanmeaninferencemachine)
- **Download:** [https://lmim.tech/download](https://lmim.tech/download)
- **Documentation:** [https://lmim.tech/docs](https://lmim.tech/docs)

---

## 📧 Contact

- **Founder:** Andrés Israel Santos Delgado
- **Email:** ops@lmim.tech
- **Twitter/X:** [@iamonthemission](https://x.com/iamonthemission)

---

## ⚠️ Disclaimer

LMIM OS is a powerful autonomous agent. It can execute shell commands, read/write files,
and send messages on your behalf. This software is provided "AS IS". The developers are
not liable for any data loss, system damage, or unintended actions. Always review critical
actions before confirming.

---

**Built with ❤️ .. Stay lean. Stay mean.**