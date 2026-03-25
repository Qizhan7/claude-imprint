# Claude Imprint

A self-hosted AI agent system built on **Claude Code**. Multi-channel chat (Telegram + WeChat + Claude.ai), persistent memory with semantic search, scheduled tasks, and a single-file dashboard — all running on your own machine.

Think of it as a DIY [OpenClaw](https://github.com/nicholasgasior/OpenClaw), but using only official Claude Code features. No third-party account authorization, all data stays local.

## Features

- **Memory System** — SQLite + FTS5 keyword search + Ollama bge-m3 vector embeddings. Hybrid search with time decay. MCP-based: Claude decides when to read/write memories.
- **Multi-Channel** — Telegram (official plugin), WeChat (via bridge), Claude.ai chat (via Cloudflare Tunnel + OAuth). All channels share the same memory.
- **Scheduled Tasks** — Persistent tasks (morning briefing, reminders, nightly memory consolidation) using Claude Code's built-in scheduler.
- **Heartbeat Agent** — Periodic automated checks with proactive notifications.
- **Dashboard** — Single-file FastAPI app (localhost:3000). Component status, start/stop controls, memory browser, interaction heatmap.
- **Pre-compaction Hook** — Automatically saves conversation context before Claude Code compresses the context window.

## Architecture

```
You ← Telegram / WeChat / Claude.ai chat
         ↓
    Claude Code (the brain)
    ├── CLAUDE.md (personality + rules)
    ├── MCP Memory Server → SQLite (memory.db)
    ├── Scheduled Tasks (persistent cron)
    └── Dashboard (localhost:3000)
```

## Prerequisites

- **Claude Code** (Pro or Max subscription recommended for heavy usage)
- **Python 3.12+**
- **macOS** (some scripts use `osascript`; Linux needs minor tweaks)

Optional:
- **Ollama + bge-m3** — for semantic vector search (works without it, keyword-only)
- **Cloudflare account** — to connect Claude.ai chat to your local memory
- **Telegram Bot** — for Telegram channel

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

### 2. Telegram

```bash
# Configure your bot token
claude /telegram:configure

# Start Telegram channel
claude --channels plugin:telegram@claude-plugins-official
```

### 3. Claude.ai Chat Integration

To access your memory from Claude.ai's web interface:

1. Start the HTTP memory server:
   ```bash
   python3.12 memory_mcp.py --http
   ```

2. Set up Cloudflare Tunnel:
   ```bash
   brew install cloudflare/cloudflare/cloudflared
   cloudflared tunnel login
   cloudflared tunnel create my-tunnel
   cloudflared tunnel route dns my-tunnel memory.yourdomain.com
   ```

3. Generate OAuth credentials:
   ```bash
   python3 -c "
   import secrets, json
   creds = {
       'client_id': secrets.token_urlsafe(16),
       'client_secret': secrets.token_urlsafe(32),
       'access_token': secrets.token_urlsafe(32),
   }
   with open('$HOME/.imprint-oauth.json', 'w') as f:
       json.dump(creds, f, indent=2)
   print('Credentials saved to ~/.imprint-oauth.json')
   print(f'Client ID: {creds[\"client_id\"]}')
   "
   ```

4. In Claude.ai → Settings → Connectors → Add Custom Connector, enter your tunnel URL and OAuth credentials.

### 4. Dashboard

```bash
python3.12 dashboard.py
# Open http://localhost:3000
```

Manages all components from one page: start/stop services, browse memories, view scheduled tasks, interaction heatmap.

### 5. Scheduled Tasks

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
