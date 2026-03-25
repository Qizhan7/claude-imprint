# Claude Imprint

A self-hosted AI agent system built on **Claude Code**. Multi-channel chat (Telegram + WeChat + Claude.ai), persistent memory with semantic search, scheduled tasks, and a single-file dashboard — all running on your own machine.

Think of it as a DIY [OpenClaw](https://github.com/openclaw/openclaw), but using only official Claude Code features. No third-party account authorization, all data stays local.

## Features

- **Unified Memory Across Claude Code and Claude.ai** — The same SQLite memory backend serves both Claude Code (local MCP server) and Claude.ai chat (via Custom Connector + Cloudflare Tunnel). Memories saved in one are instantly available in the other. One brain, multiple interfaces.
- **Custom Memory System (replaces CC's built-in memory)** — Claude Code's default memory is file-based and basic. This project replaces it with a full database-backed system: SQLite + FTS5 full-text search + Ollama bge-m3 vector embeddings. Hybrid retrieval (keyword + semantic + time decay scoring), categorized storage, daily logs, and MCP tools that let Claude autonomously decide when to remember and recall.
- **Multi-Channel (all optional)** — Pick the channels you need: Telegram (official plugin), WeChat (via bridge), Claude.ai chat (via Custom Connector). Each is independent — install one, two, or all. They share the same memory.
- **Scheduled Tasks** — Persistent tasks (morning briefing, reminders, nightly memory consolidation) using Claude Code's built-in scheduler.
- **Heartbeat Agent** — Periodic automated checks with proactive notifications.
- **Dashboard** — Single-file FastAPI app (localhost:3000). Component status, start/stop controls, memory browser, interaction heatmap.
- **Pre-compaction Hook** — Automatically saves conversation context before Claude Code compresses the context window.

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
        ├── Scheduled Tasks
        └── CLAUDE.md
```

## Prerequisites

- **Claude Code** (Pro or Max subscription recommended for heavy usage)
- **Python 3.12+**
- **macOS** (some scripts use `osascript`; Linux needs minor tweaks)
- **An always-on machine** — This is a local-first system. All services (memory server, Cloudflare Tunnel, heartbeat, scheduled tasks) run on your machine. If your computer sleeps or shuts down, they stop. For uninterrupted service, consider running on a Mac mini / home server, or disabling sleep (`caffeinate -s` on macOS).

Optional (install only what you need):
- **Telegram Bot** — for Telegram channel
- **WeChat** — via [claude-wechat-channel](https://www.npmjs.com/package/claude-wechat-channel) bridge
- **Cloudflare account** — to connect Claude.ai chat to your local memory
- **Ollama + bge-m3** — for semantic vector search (works without it, keyword-only)

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/claude-imprint.git
cd claude-imprint

# Install dependencies
pip install -r requirements.txt

# Register the memory MCP server (user-level, available in all CC sessions)
claude mcp add -s user imprint-memory -- python3.12 $(pwd)/memory_mcp.py

# Start the dashboard
python3.12 dashboard.py
# → http://localhost:3000
```

## Setup Guide

### 1. Memory System

The memory system works out of the box after registering the MCP server. Claude will automatically use `memory_remember` and `memory_search` tools.

To enable semantic search (optional):
```bash
# Install Ollama
brew install ollama
ollama pull bge-m3
```

### 2. Telegram (optional)

```bash
# Configure your bot token
claude /telegram:configure

# Start Telegram channel
claude --channels plugin:telegram@claude-plugins-official
```

### 3. WeChat (optional)

```bash
# Install the WeChat bridge
npm install -g claude-wechat-channel

# Add to your .mcp.json (see .mcp.json.example)
# Start WeChat channel
claude --dangerously-load-development-channels server:wechat
```

### 4. Claude.ai Chat Integration (optional)

This is the key feature: **Claude.ai chat and Claude Code share the same memory database.** Memories saved in a chat conversation are searchable from Claude Code, and vice versa.

The memory MCP server supports two modes — local stdio (for Claude Code) and HTTP (for Claude.ai via Custom Connector). Both read and write to the same local `memory.db`.

#### Step 1: Start the HTTP memory server

```bash
python3.12 memory_mcp.py --http
# Runs on localhost:8000
```

This runs alongside the stdio server that Claude Code already uses. They share the same database (SQLite WAL mode handles concurrent access).

#### Step 2: Expose via Cloudflare Tunnel

```bash
brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel login
cloudflared tunnel create my-tunnel
cloudflared tunnel route dns my-tunnel memory.yourdomain.com
```

Or use a free quick tunnel (temporary URL, changes on restart):
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

1. Go to **Claude.ai → Settings → Connectors → Add Custom Connector**
2. Enter your tunnel URL
3. In Advanced Settings, enter the OAuth Client ID and Client Secret
4. Click Add — done

Claude.ai now has access to `memory_remember`, `memory_search`, `memory_forget`, `memory_daily_log`, and `memory_list` — the exact same tools Claude Code uses.

#### Step 5: Teach Claude.ai to use the memory

Adding the connector gives Claude.ai access to the tools, but it won't know *when* to use them unless you tell it. A few options:

- **Project instructions** (recommended): Create a Claude.ai Project and add instructions like *"Use `memory_search` to recall context. Use `memory_remember` to save important information."*
- **Custom instructions**: In Claude.ai → Settings → Custom Instructions, add a note about using the memory tools.
- **Just ask**: You can also tell Claude in any conversation to remember or search — it will see the available tools and use them.

Once set up, the workflow is seamless: chat on Claude.ai during the day, switch to Claude Code for coding — same memories, no sync needed.

### 5. Dashboard

```bash
python3.12 dashboard.py
# Open http://localhost:3000
```

Manages all components from one page: start/stop services, browse memories, view scheduled tasks, interaction heatmap.

### 6. Scheduled Tasks

Create persistent scheduled tasks through Claude Code:
```
> Create a scheduled task that sends me a morning briefing at 8am via Telegram
```

Tasks survive restarts and are stored in `~/.claude/scheduled-tasks/`.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `TZ_OFFSET` | `0` | UTC offset for your timezone (e.g., `12` for NZST, `-5` for EST) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `EMBED_MODEL` | `bge-m3` | Embedding model name |
| `HEARTBEAT_INTERVAL` | `900` | Heartbeat interval in seconds |
| `TELEGRAM_CHAT_ID` | (empty) | Your Telegram chat ID for notifications |
| `QUIET_START` | `23` | Quiet hours start (no proactive messages) |
| `QUIET_END` | `7` | Quiet hours end |

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
├── start-all.sh         # Start all services
├── stop-all.sh          # Stop all services
└── requirements.txt
```

## How It Compares to OpenClaw

| | OpenClaw | Claude Imprint |
|---|---|---|
| Data location | Third-party servers | Your own machine |
| Account security | Requires authorization | No third-party access |
| Cost | Platform fee + API costs | Claude Code subscription |
| Setup difficulty | Low (hosted) | Medium (self-hosted) |
| Customization | Limited | Fully customizable |
| Multi-channel | Many | Telegram + WeChat + Claude.ai |

## Acknowledgements

- [OpenClaw](https://github.com/openclaw/openclaw) — The personal AI assistant framework that inspired this project
- [Anthropic](https://anthropic.com) — Claude Code, MCP protocol, and the Telegram plugin
- [FastMCP](https://github.com/jlowin/fastmcp) / [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — MCP server framework
- [claude-wechat-channel](https://www.npmjs.com/package/claude-wechat-channel) — WeChat bridge for Claude Code
- [Ollama](https://ollama.com) + [bge-m3](https://huggingface.co/BAAI/bge-m3) — Local embedding model for semantic search

## License

[MIT](LICENSE)
