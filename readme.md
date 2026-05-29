# ⚡ LMIM OS v2.1 "Tezcat · Sharpened" — Lean Mean Inference Machine

> **Codename: Tezcat · Sharpened** — The same fire. Sharper edge. More capable, more focused, more yours.

**Local-first AI operating system. No cloud. No subscription. No API fees. No compromise.**

LMIM OS bundles a full AI assistant with local LLM inference, voice, scheduling, multi-channel messaging, document intelligence, web scraping, and developer tools — all running on your hardware, over your LAN, under your control.

---

## 🆕 What's New in v2.1

### 📁 Directory Workspace
Point LMIM at any local folder and it becomes your AI coding partner. It reads, writes, creates, and edits files entirely within that sandbox — no accidental writes outside, no absolute paths.

- Native folder picker via Electron dialog
- File tree rendered live in the sidebar
- All file operations scoped to your selected root via `safe_path()` — path escape attempts are blocked at the backend
- Shell commands run inside the workspace directory by default
- Workspace context injected into every prompt so the model always knows what it's working with

### 📄 RAG Lite — Document Q&A
Upload a PDF, TXT, or Markdown file and have a focused conversation about it. No system prompt bleed, no tool calling, no distraction — just the model and your document.

- Dedicated Document tab with integrated chat, separate from the main assistant
- Drag-and-drop upload with live progress indicator
- Smart chunking that respects markdown headings, code blocks, and paragraph structure
- MMR reranking (Maximal Marginal Relevance) for diverse, non-redundant retrieval
- Suggested questions auto-generated on upload
- Two-pass retrieval: strict threshold first, broad fallback if needed
- Fully local — document never leaves your machine
- Works alongside the main chat via a collapsible sidebar drawer

### 🕷️ Web Scraper Agent
Extract and analyze web content without leaving LMIM.

- Scrape up to 10 URLs in parallel
- **Basic mode** — returns clean extracted text, metadata, title, word count, links
- **LMIM mode** — AI analyzes findings based on your stated purpose ("find pricing info and compare plans")
- Respects `robots.txt`, rate-limited, 30s timeout per URL
- Export results as JSON, copy to clipboard, or send directly to chat
- Full results panel with expandable per-URL cards and a live progress indicator

### 📇 Contacts
Your local address book, integrated with all messaging tools.

- Add contacts with name, phone, email, and notes
- Say "Send a WhatsApp to John Doe" — LMIM resolves the name automatically
- Live search across your contact list
- Integrated with Campaign Blaster and all communication daemons

### 🎯 Prime Directive
Standing instructions injected into every session — no more repeating yourself.

- Set once in the Setup Wizard or Settings tab
- Prepended to every system prompt automatically
- Use it to give LMIM a specific role: *"You are an assistant for Happy Fox English School. Always respond warmly and prioritize parent communications."*

### 🌐 Language Selection
- Choose English or Spanish in the Setup Wizard and Settings
- Language instruction injected into every prompt automatically
- Persists across restarts via `.env`

### 🧠 Improved Model Response Handling
Qwen3 and other thinking models separate their chain-of-thought from their final answer — `content` is intentionally empty, the answer lives in `reasoning_content`. LMIM now reads both fields and uses whichever is populated, so you always get a response.

- `content` → `reasoning_content` fallback in both main chat and RAG chat
- Affects all local inference paths
- No configuration needed — works automatically with any Qwen3 variant

### ⚡ Inference Hardware Controls
- Manual CPU/GPU toggle in Settings — force CPU to free VRAM, or force GPU when auto-detection fails
- Current mode displayed with VRAM stats
- One-click **Download Qwen 3.5 9B** — streams the model to `~/.lmim_os/models/`, activates on restart
- GPU mode persisted via `.env`, respected on llama-server restart

### 🛠️ CLI Tool Hardening
Every tool now returns a consistent response schema `{ok, result, tool}` — no more silent failures or inconsistent return shapes confusing the model mid-chain.

- `run_shell` — timeout, workspace-scoped `cwd`, blocked destructive commands list
- `web_search` — proper error returns on network failure
- `schedule_event` — conflict detection before write
- `memory_read` — returns plain text summary, not raw JSON blob
- Tool call parser rebuilt with four-layer fallback: strict JSON → embedded JSON → relaxed (trailing commas, single quotes) → regex last resort
- Parser unit tests added

### 🎨 UI / UX Overhaul

**Navigation**
- Nav items lift and glow on hover — emerald glow expands from the left edge, icon scales up
- Active tab gets an emerald left border
- Image Gen nav icon replaced with an animated pulsing orb (purple → indigo → emerald breathing cycle)
- New nav group labels: CORE, OPERATIONS, SERVICES, SYSTEM, INTELLIGENCE, COMING SOON

**Fonts & Colors**
- Inter + JetBrains Mono throughout — tighter, crisper, more intentional
- Emerald (`#10b981`) as the Tezcat accent color: status dots, active states, send button, scrollbars, card borders
- Cyberpunk neon outline on the model download button — transparent background, glowing emerald border, intensifies on hover

**New Tabs**
- **Workspace** — full file tree, folder picker, preview pane, quick-prompt shortcuts
- **Document Q&A** — dedicated RAG chat with suggested questions, drag-drop upload, clear/reset
- **Web Scraper** — two-panel layout, URL list with numbered rows, mode toggle, results with expandable cards
- **Contacts** — add form, live search, avatar initials, example commands panel

**Stub Tabs (building anticipation)**
- **🛡 Horus Security** (v3.0) — vault aesthetic, scan-line animation, pulsing shield rings, feature preview list, "Notify me" link
- **🎨 Image Generation** (v2.2) — three-ring animated orb, mock canvas with shimmer grid, prompt chips, wishlist capture

**Setup Wizard**
- Now includes Prime Directive field (with example for Happy Fox English School)
- Language selection (English / Español)
- Wizard completion triggers onboarding tour automatically

**Onboarding Tour**
- Rebuilt from 7 steps to 11 — covers Workspace, Document Mode, Web Scraper, Contacts, Voice, Settings/Prime Directive, Horus, Image Gen
- Action-first step descriptions — tells users what to *do*, not just what a feature *is*
- "Show Tour" button lives in the sidebar status box, appears after first run
- `localStorage` flag prevents re-showing after first completion while keeping manual relaunch available

---

## 📦 What's Unchanged from v2.0

Everything that shipped in Tezcat is still here, still works, still fast:

- One-click AppImage (Linux) and Windows installer
- CUDA acceleration — llama.cpp and whisper.cpp GPU inference
- Voice engine — Whisper STT + Piper TTS, 5 languages, auto-speak
- WhatsApp, Telegram, Email, Slack, Discord daemons
- Campaign Blaster — bulk WhatsApp/Email from CSV
- FullCalendar visual agenda with natural language scheduling
- Developer Toolbox — hash checker, CSS/JS minifier, JSON validator
- Planner → Builder → Inspector autonomous build loop
- Persistent memory and multi-conversation chat
- Cloud fallback — OpenAI, Anthropic, Groq with one toggle
- System diagnostics — CPU, RAM, disk, uptime

---

## 📦 Installation

### Prerequisites
- **Linux** (Ubuntu 22.04+ recommended, Fedora 40+ supported) · **Windows** 10/11
- **Python 3.10+** with pip
- **Node.js 18+** (for WhatsApp daemon)
- **CUDA Toolkit 12.x** + **NVIDIA driver 545+** (optional — for GPU acceleration)

### Quick Start
```bash
chmod +x LMIM_OS_*.AppImage
./LMIM_OS_*.AppImage
```

### From Source
```bash
git clone https://github.com/leanmeaninferencemachine/leanmeaninferencemachine
cd leanmeaninferencemachine
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
npm install
python3 run_app_backend.py
```

### First Launch
1. Complete the Setup Wizard — name, assistant name, tone, language, Prime Directive
2. Accept the safety disclaimer
3. Take the onboarding tour (11 stops, ~3 minutes)
4. Select your workspace folder in the Workspace tab
5. For GPU: ensure CUDA is installed, toggle Local mode in Settings

---

## 🚀 Performance

| Task | CPU (i7-12700H) | GPU (GTX 1650 Ti, 4GB) | GPU (RTX 3060, 12GB) |
|------|-----------------|------------------------|----------------------|
| LLM prompt processing | ~50 tok/s | ~900 tok/s | ~2500 tok/s |
| LLM token generation (2B) | ~5 tok/s | ~80 tok/s | ~120 tok/s |
| LLM token generation (0.8B) | ~10 tok/s | ~85 tok/s | ~150 tok/s |
| Whisper STT (small, 5s audio) | ~7s | ~0.5s | ~0.3s |
| Piper TTS | <1s | <1s | <1s |
| RAG embedding (all-MiniLM-L6-v2, CPU) | ~1-3s per doc | — | — |

---

## 🏗️ Architecture

```
LMIM OS v2.1
├── llama.cpp/              — LLM inference (GPU via CUDA)
├── whisper.cpp/            — Speech-to-text (GPU via CUDA)
├── voice/
│   ├── bin/                — piper, whisper-cli
│   └── models/stt|tts/     — Whisper + Piper model files
├── app/
│   ├── main.py             — Flask server + all API endpoints
│   ├── router.py           — Intent routing
│   ├── model_interface.py  — LLM inference wrapper (local + cloud)
│   ├── rag.py              — Document ingestion, chunking, MMR retrieval
│   ├── workspace.py        — Directory workspace + safe_path sandbox
│   ├── voice_service.py    — STT/TTS helpers
│   ├── agents/             — WhatsApp, Telegram, Planner, Builder, Inspector
│   ├── tools/              — file, shell, search, scraper, scheduling, memory
│   └── memory/             — Episodic, semantic, conversation summary
├── daemons/                — WhatsApp (Baileys), Telegram, Email, Slack, Discord
├── electron/               — Desktop wrapper
├── models/                 — Bundled GGUF models + embedding model
├── templates/              — Dashboard (HTML, CSS, JS)
└── data/                   — Runtime: memories, logs, RAG store, agendas
```

---

## 📁 Data Locations

| Purpose | Path |
|---------|------|
| User config | `~/.lmim_os/.env` |
| Identity | `~/.lmim_os/config/user_identity.json` |
| Memories | `~/.lmim_os/memories/` |
| RAG documents | `~/.lmim_os/data/rag/` |
| Downloaded models | `~/.lmim_os/models/` |
| Logs | `~/.lmim_os/logs/` |
| WhatsApp auth | `~/.lmim_os/whatsapp/auth/` |

---

## 🔗 Links

- **Website:** [https://lmim.tech](https://lmim.tech)
- **GitHub:** [https://github.com/leanmeaninferencemachine/leanmeaninferencemachine](https://github.com/leanmeaninferencemachine/leanmeaninferencemachine)
- **Download:** [https://lmim.tech/download](https://lmim.tech/download)

---

## 📧 Contact

- **Founder:** Andrés Israel Santos Delgado
- **Email:** ops@lmim.tech
- **Twitter/X:** [@iamonthemission](https://x.com/iamonthemission)

---

## ⚠️ Disclaimer

LMIM OS is a powerful autonomous agent. It can execute shell commands, read/write files, and send messages on your behalf. This software is provided "AS IS". The developers are not liable for any data loss, system damage, or unintended actions. Always review critical actions before confirming.

---

**Built with ❤️ in Tijuana. Stay lean. Stay mean.**
