# ⚡ LMIM: Lean Mean Inference Machine

> **The unified, self-hosted AI operating system for agents, automation, and hybrid inference.**

LMIM is a high-performance orchestration engine that bridges local LLMs (via `llama.cpp`) with cloud providers (Groq, OpenAI, Anthropic) in a single, seamless interface. Built for privacy, scalability, and absolute control.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Status](https://img.shields.io/badge/status-beta-orange.svg)

## 🚀 Features

### 🧠 Hybrid Inference Engine
- **Local First:** Run quantized models (Qwen, Llama 3, Mixtral) locally via `llama-server` with full privacy.
- **Cloud Bursting:** Seamlessly switch to **Groq**, **OpenAI**, or **Anthropic** for speed or complex reasoning without changing your workflow.
- **Dynamic Routing:** Configure temperature, context window, and provider per session via the GUI.

### 💾 Persistent Smart Memory
- **User Isolation:** Each user gets a dedicated sandbox (`data/memories/users/{id}/`) with isolated chat history, semantic memory, and state.
- **Auto-Summarization:** Intelligent background summarization keeps context fresh without bloating the prompt.
- **Tool-Augmented Recall:** The AI actively decides when to save facts or retrieve past conversations using built-in tools.

### 🤖 Multi-Channel Daemons
- **Unified Inbox:** Connect **WhatsApp**, **Telegram**, **Slack**, **Discord**, and **Email** into a single conversational stream.
- **Event-Driven Architecture:** Asynchronous workers handle incoming messages and outbound queues reliably.
- **Campaign Blaster:** Built-in bulk messaging tool for newsletters or announcements (CSV-driven).

### 🎨 Glassmorphism Unified Console
- **All-in-One Dashboard:** Monitor daemon health, view live logs, manage agendas, and chat with your AI in a stunning, translucent UI.
- **Visual Agenda:** Integrated calendar for scheduling meetings directly via chat commands.
- **Build System:** Watch AI-generated code being written, tested, and deployed in real-time logs.

## 🏗️ Architecture

```mermaid
graph TD
    User[User Interfaces] -->|HTTP/Webhook| Router[Central Router]
    Router -->|Intent Detection| Agent{Agent Selector}
    
    Agent -->|Chat/Memory| Core[Inference Engine]
    Agent -->|Code Gen| Builder[Builder Worker]
    Agent -->|Schedule| Calendar[Agenda System]
    
    Core -->|Local| Llama[llama-server (GPU/CPU)]
    Core -->|Cloud| API[Groq / OpenAI / Anthropic]
    
    Core <--> Mem[(Persistent JSON Memory)]
    
    Daemons[Communication Daemons] -->|WA/TG/Slack/Email| Router
    Daemons -->|Queue| Outbound[(Outbound Queue)]
