# Claude Imprint

### One Claude. Unified memory. Every channel. Your personal assistant that lives across all your devices.

A self-hosted system that gives Claude persistent memory and connects it across Claude Code, Claude.ai, Telegram, and WeChat. Talk to it from your terminal, your browser, or your phone — it remembers everything, shares context across channels, writes code on your machine from anywhere, and manages your day. All data stays local.

Built for **Claude Code Pro/Max subscribers** who want to unlock more from their subscription. Uses only official Claude Code features — no API costs, no third-party authorization. Think of it as a DIY [OpenClaw](https://github.com/openclaw/openclaw), fully local and fully yours.

## Features

### 🧠 Memory
- **Custom Memory System (replaces CC's built-in)** — Claude Code's default memory is file-based and basic. This replaces it with SQLite + FTS5 full-text search + bge-m3 vector embeddings. Hybrid retrieval (keyword + semantic + time decay scoring), categorized storage, and daily logs.
- **Unified Memory Across Claude Code and Claude.ai** — The same SQLite backend serves both Claude Code (local stdio MCP) and Claude.ai chat (HTTP MCP via Cloudflare Tunnel). One brain, multiple interfaces — memories saved in one are instantly searchable from the other.
- **Categorized Storage** — Memories are tagged by type (facts, events, tasks, experience) and source (cc, telegram, wechat, chat). Search by category or let hybrid search find the best match.
- **Knowledge Bank** — Long-form structured knowledge in Markdown files (`memory/bank/`). Preferences, relationships, technical experience — all indexed and included in semantic search automatically.
- **Daily Logs** — Automatic daily journals (`memory/YYYY-MM-DD.md`). Pre-compaction hooks capture conversation context before it's compressed. Nothing gets lost.
- **Auto-generated Index** — `MEMORY.md` is rebuilt on every write, giving Claude a quick snapshot of what's stored without querying the database.

### 💬 Multi-Channel
- **Chat From Anywhere** — Telegram, WeChat, Claude.ai, or any future platform. Each channel is independent and optional — install one or all. They all share the same memory.
- **Cross-Channel Memory** — Ask Claude to recall something from Telegram while you're on Claude.ai. What you said on your phone is available at your computer.
- **Message Bus (Cross-Channel Context)** — Messages flow in from Telegram, WeChat, Claude.ai, scheduled tasks — Claude keeps a shared timeline of what happened where. When you switch devices or channels, it already knows the context. No need to repeat yourself.

### 🎮 Remote Control (via Claude.ai Chat)
- **Chat-to-Code** — Tell Claude.ai to write code, run scripts, fix bugs, or manage git repos on your computer. Claude.ai submits the task → local Claude Code executes it → results come back. Your phone becomes a remote terminal.
- **Direct Telegram Messaging** — Claude.ai can send messages and files to your Telegram instantly via Bot API — no Claude Code middleman, millisecond delivery.
- **System Monitor** — Check your computer's CPU, RAM, disk usage, and which services are running — all from Claude.ai chat.
- **Webpage Reader** — Ask Claude.ai to fetch and read any URL for you. "Summarize this article" works even from your phone.
- **Spotify Control** — Play, pause, skip, adjust volume on your Mac's Spotify — from Claude.ai chat (macOS only).
- **Morning Briefing** — Weather + calendar + pending tasks, composed and sent to your Telegram in one message.

### ⚡ Automation
- **Scheduled Tasks** — Persistent tasks (morning briefing, reminders, nightly memory consolidation) using Claude Code's built-in scheduler. "Remind me to drink water at 3pm every day" — done.
- **Heartbeat Agent** — Periodic automated checks with proactive Telegram notifications.
- **Pre-compaction Hook** — Saves conversation context before Claude Code compresses the window, so nothing important gets lost.

### 📊 Dashboard
- **Control Panel** — Single-file FastAPI app (localhost:3000). Start/stop services, browse memories, view scheduled tasks, and a GitHub-style interaction heatmap showing your daily activity with Claude over the past year.
- **Remote Tool Log** — See what Claude.ai has been doing on your machine: task submissions, Telegram messages sent, tool calls — all in one place.

## Architecture

```
                        ┌─────────────────┐
                        │   memory.db     │  ← single source of truth
                        │  (SQLite local) │
                        └────────┬────────┘
                                 │
                ┌────────────────┼────────────────┐
                │ stdio          │ HTTP            │
                ▼                ▼                 ▼
        Claude Code        Cloudflare Tunnel   Dashboard
        ├── Telegram       → Claude.ai chat    (localhost:3000)
        ├── WeChat            (Custom Connector)
        ├── Scheduled Tasks        │
        └── CLAUDE.md              │
                │                  │
                └──── message_bus ──┘  ← cross-channel context
```

## Prerequisites

- **Claude Code** (Pro or Max subscription recommended for heavy usage)
- **Python 3.11+**
- **macOS or Linux** — Core features (memory, MCP server, dashboard) work on both. Shell scripts (`start-all.sh`, `stop-all.sh`) use `osascript` to open Terminal windows on macOS; on Linux, replace with your terminal emulator or run each service manually.
- **An always-on machine** — This is a local-first system. All services (memory server, Cloudflare Tunnel, heartbeat, scheduled tasks) run on your machine. If your computer sleeps or shuts down, they stop. For uninterrupted service, consider running on a Mac mini / home server, or disabling sleep (`caffeinate -s` on macOS). `start.sh` will use `caffeinate` automatically when available, and falls back to a normal background process on Linux.

Optional (install only what you need):
- **Telegram Bot** — for Telegram channel
- **WeChat** — via [claude-wechat-channel](https://www.npmjs.com/package/claude-wechat-channel) bridge
- **Cloudflare account** — to connect Claude.ai chat to your local memory
- **Ollama + bge-m3** — for semantic vector search (works without it, keyword-only)

## Quick Start

```bash
# Clone
git clone https://github.com/Qizhan7/claude-imprint.git
cd claude-imprint

# (Recommended) Create a virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Register the memory MCP server (user-level, available in all CC sessions)
claude mcp add -s user imprint-memory -- python3 $(pwd)/memory_mcp.py

# Start the dashboard
python3 dashboard.py
# → http://localhost:3000
```

> **Note:** This guide uses `python3` throughout. If you have multiple Python versions, replace with `python3` or whichever version you have (3.11+ required).

## Setup Guide — Pick What You Need

After running Quick Start, you have the memory system working locally. Choose which modules to add:

| I want to... | Module |
|---|---|
| Just have persistent memory in Claude Code | ✅ Already done (Quick Start) |
| Connect Claude.ai chat to the same memory | → [Module A: Chat Integration](#module-a-chat-integration) |
| Talk to Claude from my phone | → [Module B: Telegram](#module-b-telegram) or [Module C: WeChat](#module-c-wechat) (pick one or both) |
| Let Claude.ai control my computer | → [Module A](#module-a-chat-integration) (includes `cc_execute`) |
| Automated heartbeat / reminders | → [Module D: Automation](#module-d-automation) |
| Dashboard to manage everything | → [Module E: Dashboard](#module-e-dashboard) |
| Import old Claude.ai conversations | → [Module F: Chat Import](#module-f-chat-import) |

---

### First: Write Your CLAUDE.md

Before setting up any module, create `~/.claude/CLAUDE.md`. This is what makes Claude *yours*:

```markdown
# My Assistant

## About Me
- Name: [your name]
- Timezone: [e.g., UTC-5, UTC+8]
- Languages: [e.g., English, Chinese]

## Personality
- [casual? formal? concise? playful?]

## Memory Rules
- Save important information using memory_remember
- Search memory before saying "I don't know"

## Notification Rules
- Telegram chat_id: [your chat ID]
- Quiet hours: 23:00-07:00
```

See [Customization: The .md Files](#customization-the-md-files) for the full file structure.

### First: Pre-compaction Hook (recommended)

Saves conversation context before Claude Code compresses the window:

```bash
claude settings add-hook PreCompact "bash $(pwd)/hooks/pre-compact-flush.sh"
```

### Optional: Semantic Search

Adds AI-powered meaning-based search on top of keyword search:
```bash
brew install ollama && ollama pull bge-m3
```

---

### Module A: Chat Integration

**What you get:** Claude.ai chat shares the same memory as Claude Code. Plus: `send_telegram` (direct messaging), `cc_execute` (remote code execution), `system_status`, `read_webpage`, `spotify_control`, `morning_briefing` — all accessible from Claude.ai.

**You need:** A domain (or free Cloudflare quick tunnel), Cloudflare account.

#### Step 1: Start the HTTP server

```bash
# Set env vars for Telegram integration (optional but recommended)
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"

# For weather in morning briefing (optional)
export WEATHER_LAT="40.71"    # your latitude
export WEATHER_LON="-74.01"   # your longitude
export WEATHER_TZ="America/New_York"

# Start
python3 memory_mcp.py --http
# Runs on localhost:8000
```

#### Step 2: Expose via Cloudflare Tunnel

**Option A — Permanent tunnel (recommended)**
```bash
brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel login
cloudflared tunnel create my-tunnel
cloudflared tunnel route dns my-tunnel memory.yourdomain.com
```

**Option B — Free quick tunnel (no domain needed, URL changes on restart)**
```bash
cloudflared tunnel --url http://localhost:8000
```

#### Step 3: Generate OAuth credentials

```bash
python3 -c "
import secrets, json
creds = {
    'client_id': secrets.token_urlsafe(16),
    'client_secret': secrets.token_urlsafe(32),
    'access_token': secrets.token_urlsafe(32),
}
with open('\$HOME/.imprint-oauth.json', 'w') as f:
    json.dump(creds, f, indent=2)
print('Credentials saved to ~/.imprint-oauth.json')
print(f'Client ID: {creds[\"client_id\"]}')
"
```

#### Step 4: Add Custom Connector in Claude.ai

1. **Claude.ai → Settings → Connectors → Add Custom Connector**
2. Enter your tunnel URL
3. In Advanced Settings, enter OAuth Client ID and Client Secret
4. Click Add — done

#### Step 5: Teach Claude.ai to use it

Add to Claude.ai **Custom Instructions** or **Project Instructions**:

> *Use `memory_search` before answering questions about me. Use `memory_remember` to save important info. Use `send_telegram` to message me. Use `cc_execute` to run tasks on my computer.*

**Available tools via Chat Integration:**

| Tool | What it does |
|---|---|
| `memory_remember/search/forget/list` | Read & write shared memory |
| `send_telegram` | Send text message to Telegram |
| `send_telegram_photo` | Send file/photo to Telegram |
| `cc_execute` | Run a task on your computer via Claude Code |
| `cc_check` / `cc_tasks` | Check task status |
| `system_status` | CPU, RAM, disk, service health |
| `read_webpage` | Fetch & extract text from a URL |
| `spotify_control` | Play/pause/skip/volume (macOS) |
| `morning_briefing` | Weather + calendar + tasks → Telegram |
| `message_bus_read` | Read recent cross-channel message history |
| `message_bus_post` | Write to the shared cross-channel context |
| `memory_daily_log` | Append to today's daily log |

---

### Module B: Telegram

**What you get:** Talk to Claude from Telegram. Full Claude Code capabilities.

**You need:** A Telegram bot token (from [@BotFather](https://t.me/BotFather)).

```bash
# 1. Configure bot token
claude /telegram:configure

# 2. Start (with auto-approve for safe operations)
claude --permission-mode auto --channels plugin:telegram@claude-plugins-official
```

> **Tip:** Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot) on Telegram.

---

### Module C: WeChat

**What you get:** Talk to Claude from WeChat.

**You need:** npm, a WeChat account.

```bash
# 1. Install bridge
npm install -g claude-wechat-channel

# 2. Configure (see .mcp.json.example)

# 3. Start
claude --permission-mode auto --dangerously-load-development-channels server:wechat
# Scan QR code with WeChat to link
```

---

### Module D: Automation

**What you get:** Heartbeat agent (periodic checks + proactive notifications), scheduled tasks (morning briefing, reminders).

**You need:** At least one chat channel set up ([Module B: Telegram](#module-b-telegram) or [Module C: WeChat](#module-c-wechat)) for notifications.

```bash
# Start heartbeat agent
python3 agent.py

# Or with custom interval
HEARTBEAT_INTERVAL=300 python3 agent.py   # 5-min for testing
```

Edit `SOUL.md` (personality) and `HEARTBEAT.md` (checklist) to customize behavior.

**Scheduled tasks** — ask Claude Code directly:
```
> Create a scheduled task that sends me a morning briefing at 8am via Telegram
> Create a reminder to drink water every day at 3pm
```

Tasks persist in `~/.claude/scheduled-tasks/` and survive restarts.

---

### Module E: Dashboard

**What you get:** A single-page control panel for your entire system.

- **Service Manager** — Start/stop all services (Memory HTTP, Cloudflare Tunnel, Telegram, WeChat) with toggle switches. Background services show logs inline.
- **Status Bar** — Tunnel URL, total memory count, today's log count at a glance.
- **Interaction Heatmap** — GitHub-style 365-day activity chart. Darker = more interactions that day.
- **Scheduled Tasks** — View all recurring tasks (morning briefing, reminders, nightly consolidation).
- **Remote Tool Log** — See what Claude.ai chat has been doing: task submissions, results, Telegram messages sent.
- **Memory Browser** — Search, edit, and delete memories directly. Changes sync to the database in real-time (including vector embeddings and full-text index).
- **Language Toggle** — Switch between English and Chinese (🌐 button, top right). Preference is saved in localStorage.

```bash
python3 dashboard.py
# → http://localhost:3000
```

![Dashboard Screenshot](docs/dashboard.png)

---

### Module F: Chat Import

**What you get:** Import old Claude.ai conversations into the memory system.

```bash
# 1. Export from Claude.ai: Settings → Privacy → Export Data
# 2. Unzip, find conversations.json
python3 chat_cleaner.py ~/Downloads/claude-export/conversations.json

# 3. Feed sessions to Claude Code for memory extraction
claude "Read chat_sessions/session_001.txt and save important facts to memory using memory_remember"
```

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `TZ_OFFSET` | `0` | UTC offset for your timezone (e.g., `12` for NZST, `-5` for EST) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `EMBED_MODEL` | `bge-m3` | Embedding model name |
| `HEARTBEAT_INTERVAL` | `900` | Heartbeat interval in seconds |
| `TELEGRAM_BOT_TOKEN` | (empty) | Telegram bot token (from @BotFather) |
| `TELEGRAM_CHAT_ID` | (empty) | Your Telegram chat ID (from @userinfobot) |
| `QUIET_START` | `23` | Quiet hours start (no proactive messages) |
| `QUIET_END` | `7` | Quiet hours end |
| `WEATHER_LAT` | `0` | Latitude for weather in morning briefing |
| `WEATHER_LON` | `0` | Longitude for weather in morning briefing |
| `WEATHER_TZ` | `UTC` | Timezone name for weather (e.g., `America/New_York`) |

## File Structure

```
claude-imprint/
├── memory_manager.py    # Core memory module (SQLite + vectors + FTS5)
├── memory_mcp.py        # MCP server (stdio + HTTP modes)
├── dashboard.py         # Single-file dashboard (FastAPI + inline HTML)
├── heartbeat.py         # Heartbeat agent module
├── agent.py             # Agent entry point
├── chat_cleaner.py      # Import old Claude.ai conversations
├── hooks/
│   └── pre-compact-flush.sh  # Pre-compaction memory saver
├── memory/              # Daily logs (YYYY-MM-DD.md)
│   └── bank/            # Structured knowledge files
├── SOUL.md              # Heartbeat personality rules
├── HEARTBEAT.md         # Heartbeat checklist
├── MEMORY.md            # Auto-generated memory index
├── start-all.sh         # Start all services (macOS Terminal)
├── stop-all.sh          # Stop all services
├── start.sh             # Start heartbeat agent (with caffeinate)
├── stop.sh              # Stop heartbeat agent
└── requirements.txt
```

## Customization: The .md Files

Claude Imprint uses a set of Markdown files that work together to give Claude its personality, behavior rules, and context. Here's what each does and how they relate:

```
~/.claude/CLAUDE.md          ← You write this. The brain.
    │
    ├── references ──→  SOUL.md         ← You write this. Lightweight personality summary.
    ├── references ──→  HEARTBEAT.md    ← You write this. What to check and when to notify.
    └── references ──→  MEMORY.md       ← Auto-generated. Don't edit.
                         memory/bank/   ← You write these. Structured knowledge.
```

### `~/.claude/CLAUDE.md` — The brain (you write this)

This is the most important file. Claude Code reads it at the start of every session. Put everything here that Claude should **always know**:

- Who you are, your preferences, your timezone
- Claude's personality and communication style
- Rules for when to remember, when to notify, when to stay quiet
- Technical preferences and project guidelines

This file lives in `~/.claude/` (not in the project directory) so it applies across all Claude Code sessions.

### `SOUL.md` — Heartbeat personality (you write this)

A lightweight subset of your CLAUDE.md, injected into heartbeat sessions. Heartbeat runs in its own session with limited context, so it needs a compact version of the personality rules. Keep it short — just behavior rules and notification preferences.

### `HEARTBEAT.md` — Heartbeat checklist (you write this)

Defines what the heartbeat agent checks on each wake-up: morning briefing, routine monitors, notification channels, quiet hours. Edit this to add your own automated checks.

### `MEMORY.md` — Memory index (auto-generated)

Auto-generated by `memory_manager.py`. Provides a quick overview of what's stored in `memory.db`. Don't edit manually — it gets overwritten.

### `memory/bank/` — Structured knowledge (you or Claude write these)

Long-form knowledge files that get indexed for semantic search:

- **`preferences.md`** — Your preferences, habits, dietary needs, etc.
- **`experience.md`** — Technical lessons learned, debugging insights
- **`relationships.md`** — People you mention, their roles and context

You can edit these directly with any text editor, or just tell Claude in conversation — "remember that I'm lactose intolerant" — and it will write to the appropriate file. You can also add new `.md` files here for any category you want; they'll automatically be included in semantic search.

### `memory/YYYY-MM-DD.md` — Daily logs (auto-generated)

Created automatically by the `memory_daily_log` tool and the pre-compaction hook. One file per day, append-only. You don't need to edit these.

### Getting Started

1. Copy the example files in this repo as a starting point
2. Write your `~/.claude/CLAUDE.md` — this is where you define who Claude is to you
3. Edit `SOUL.md` and `HEARTBEAT.md` to match your preferences
4. Add your info to `memory/bank/preferences.md`
5. The rest (MEMORY.md, daily logs) will populate automatically as you use the system

## How It Compares to Dispatch (Official)

[Dispatch](https://claude.com/blog/dispatch-and-computer-use) is Anthropic's official phone-to-desktop remote control, launched March 2026 as part of Cowork. It lets you assign tasks from the Claude mobile app to your desktop. Here's how it compares:

| | Dispatch | Claude Imprint |
|---|---|---|
| **Interface** | Claude mobile app only, single persistent thread | Any Claude.ai chat window + Telegram + WeChat + CLI |
| **Routes to** | Cowork (knowledge work) + Claude Code (dev tasks) | Claude Code only, but with custom MCP tools that cover most knowledge-work use cases |
| **Memory** | Session memory (within the thread) | Persistent SQLite + vector search, survives across sessions and channels |
| **Monitoring** | Desktop app shows live progress | Dashboard (localhost:3000) with task log, memory browser, heatmap |
| **Channels** | Phone ↔ Desktop only | Multi-channel: Telegram, WeChat, Claude.ai, Claude Code — all sharing context |
| **Customization** | None — standard Claude personality | Fully custom: personality, tools, notification rules, memory categories |
| **Computer Use** | Screenshot + click loop (can control any app) | MCP tools + shell commands (faster, but no GUI control) |
| **Scheduling** | Built-in scheduled tasks | Claude Code scheduled tasks + custom heartbeat agent |
| **Setup** | Zero — built into Claude Desktop | Manual setup, but fully open-source and extensible |
| **Platform** | macOS / Windows (no Linux) | macOS / Linux |
| **Status** | Research preview (official, polished) | Community project (DIY, flexible) |

**When to use Dispatch:** You want a polished, zero-setup mobile remote control that "just works" — especially if you need Cowork's connectors (Google Calendar, Slack, etc.) or GUI-level computer control.

**When to use Claude Imprint:** You want persistent memory that survives across sessions, multi-channel access (not just phone app), a custom personality, or full control over how your AI assistant behaves. You're comfortable with self-hosting and want to extend the system yourself.

**Can you use both?** Yes. They solve overlapping but different problems. Dispatch is great for quick phone-to-desktop tasks; Imprint is great for long-term memory, multi-channel presence, and customization.

---

## How It Compares to OpenClaw

OpenClaw is a mature, feature-rich project with a large plugin ecosystem. Claude Imprint takes a different approach — minimal, Claude Code-native, and fully local.

| | OpenClaw | Claude Imprint |
|---|---|---|
| Approach | Platform with plugin ecosystem | Lightweight, Claude Code-native |
| AI models | 20+ providers (Claude, GPT, Gemini...) | Claude only (via Claude Code) |
| Data location | Depends on provider | Fully local |
| Multi-channel | 20+ (WhatsApp, Slack, Discord...) | Telegram + WeChat + Claude.ai |
| Setup | npm install, hosted options available | Self-hosted, manual setup |
| Best for | Users who want a ready-to-go platform | Users who want full control over a Claude Code-based setup |

## Acknowledgements

- [OpenClaw](https://github.com/openclaw/openclaw) — Multi-model personal AI assistant framework that inspired this project
- [Anthropic](https://anthropic.com) — Claude Code, MCP protocol, and the Telegram plugin
- [FastMCP](https://github.com/jlowin/fastmcp) / [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — MCP server framework
- [claude-wechat-channel](https://www.npmjs.com/package/claude-wechat-channel) — WeChat bridge for Claude Code
- [Ollama](https://ollama.com) + [bge-m3](https://huggingface.co/BAAI/bge-m3) — Local embedding model for semantic search

## License

[MIT](LICENSE)
