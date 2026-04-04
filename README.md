# Claude Imprint

A self-hosted system that gives Claude persistent memory, multi-channel messaging, and automation. Talk to it from Claude Code, Claude.ai, or Telegram — it remembers everything and shares context across channels. Other channels (Discord, Slack, etc.) can be added via their own MCP servers.

Built for **Claude Code Pro/Max subscribers**. Uses only official Claude Code features — no API costs, no third-party auth.

> **Just want persistent memory?** The memory system is a standalone package: [imprint-memory](https://github.com/Qizhan7/imprint-memory). Install it alone with `pip install` — no need for the full Imprint stack. This repo adds multi-channel messaging, automation, dashboard, and everything else on top.

## Features

### 🧠 Memory
- **Hybrid search** — FTS5 full-text + bge-m3 vector embeddings + exact-match keyword, fused with RRF ranking and time-decay scoring. Replaces Claude Code's built-in file-based memory.
- **CJK support** — Chinese/Japanese/Korean text segmented with jieba for accurate full-text search.
- **Unified across interfaces** — The same SQLite backend serves Claude Code (stdio MCP) and Claude.ai (HTTP MCP via Cloudflare Tunnel). Memories saved in one are instantly searchable from the other.
- **Categorized storage** — Memories tagged by type (facts, events, tasks, experience) and source. Search by category or let hybrid search find the best match.
- **Knowledge bank** — Long-form structured knowledge in Markdown files (`memory/bank/`). Preferences, relationships, technical experience — all indexed and included in semantic search.
- **Daily logs** — Automatic daily journals. Pre-compaction hooks capture context before it's compressed. Nothing gets lost.

### 💬 Multi-Channel
- **Telegram** (primary) — Full-featured: chat, file sharing, heartbeat notifications, morning briefings, direct messaging from Claude.ai. Uses Anthropic's official Claude Code Telegram plugin.
- **Claude.ai** — Connect via Cloudflare Tunnel. Full memory access + remote code execution on your machine.
- **Cross-channel context** — Messages flow in from all sources. Claude keeps a shared timeline of what happened where. When you switch devices, it already knows the context.
- **Pluggable channels** — The system auto-detects any Claude Code channel plugin (Discord, Slack, etc.). Just install the MCP server and messages are automatically logged, tagged, and searchable.

### 🎮 Remote Control
- **Chat-to-code** — Tell Claude.ai to write code, run scripts, fix bugs on your computer. Claude.ai submits the task → local Claude Code executes it → results come back.
- **Direct Telegram messaging** — Claude.ai can send messages and files to your Telegram instantly via Bot API.
- **System monitor** — Check CPU, RAM, disk, running services — all from Claude.ai chat.
- **Webpage reader** — Fetch and read any URL from Claude.ai chat.
- **Spotify control** — Play, pause, skip, volume from Claude.ai chat. macOS only (AppleScript).

### ⚡ Automation
- **Scheduled tasks** — Morning briefing, reminders, nightly memory consolidation. Customizable cron prompt templates.
- **Heartbeat agent** — Periodic automated checks with proactive Telegram notifications.
- **Hooks** — Pre-compaction context saver + post-response conversation logger with auto-compression.

### 📊 Dashboard
- **Control panel** — Single-file FastAPI app (localhost:3000). Start/stop services, browse memories, view scheduled tasks, conversation stream stats, and a GitHub-style interaction heatmap.

![Dashboard](docs/dashboard.png)

## Platform support

| Feature | macOS | Linux / Cloud |
|---------|-------|---------------|
| Memory system, dashboard, hooks, cron | ✅ | ✅ |
| Telegram, Claude.ai integration | ✅ | ✅ |
| `start.sh` / `stop.sh` | ✅ Terminal windows | ✅ Background processes |
| Spotify control | ✅ | ❌ AppleScript only |

### Cloud server deployment

Core features (memory, HTTP server, dashboard, Telegram, heartbeat, cron) work on Linux cloud servers. Claude Code runs as a CLI tool — a basic VPS (1 CPU, 1GB RAM) is sufficient; the AI inference happens on Anthropic's servers, not yours.

```bash
# Quick start on a cloud server
git clone https://github.com/Qizhan7/claude-imprint.git && cd claude-imprint
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Authenticate Claude Code (Max Plan OAuth token)
mkdir -p ~/.claude && echo "your-token" > ~/.claude/cron-token

./start.sh   # starts all services as background processes
./stop.sh    # stops everything
```

For production deployments, systemd service templates are provided in [`deploy/`](deploy/). See [`deploy/README.md`](deploy/README.md) for full instructions.

## Quick start

```bash
git clone https://github.com/Qizhan7/claude-imprint.git
cd claude-imprint

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Register memory MCP server
claude mcp add -s user imprint-memory -- imprint-memory

# Start dashboard
python3 packages/imprint_dashboard/dashboard.py
# → http://localhost:3000
```

You now have persistent memory in Claude Code. Add modules below for more.

## Modules

### Chat integration (Claude.ai → local memory)

Connect Claude.ai to your local memory via Cloudflare Tunnel + HTTP MCP.

```bash
# 1. Start HTTP server
imprint-memory --http   # → localhost:8000

# 2. Expose via tunnel
cloudflared tunnel --url http://localhost:8000

# 3. Generate OAuth credentials
python3 scripts/generate_oauth.py

# 4. Claude.ai → Settings → Connectors → Add Custom Connector
#    Enter tunnel URL + OAuth credentials
```

### Telegram

```bash
claude /telegram:configure
claude --permission-mode auto --channels plugin:telegram@claude-plugins-official
```

### Automation

```bash
# Heartbeat agent (periodic checks + Telegram notifications)
python3 packages/imprint_heartbeat/agent.py

# Cron tasks — use prompt templates in cron-prompts/
bash cron-task.sh morning-briefing cron-prompts/morning-briefing.md
```

Cron templates: `morning-briefing.md`, `drink-water.md`, `health-check.md`, `nightly-consolidation.md`, `weekly-memory-audit.md`. Edit to fit your style and schedule with crontab.

### Hooks

```bash
# Save context before compaction
claude settings add-hook PreCompact "bash $(pwd)/hooks/pre-compact-flush.sh"

# Log conversations after each response
claude settings add-hook Stop "bash $(pwd)/hooks/post-response.sh"
```

### Adding other channels (Discord, Slack, etc.)

The system auto-detects any Claude Code channel plugin. No code changes needed — just install the channel MCP and everything works:

1. **Install the channel's MCP server** (e.g. a Discord MCP from the community)
2. **Register it in `.mcp.json`** alongside imprint-memory
3. **Start Claude Code** with both the channel and imprint-memory loaded

What happens automatically:
- **Memory** — `memory_remember`, `memory_search`, etc. work immediately
- **Conversation logging** — The post-response hook detects the new channel by name and tags all messages with the correct platform (e.g. `discord`)
- **Cross-channel context** — Messages appear in `recent_context.md` and the CLAUDE.md AUTO section, visible to all other channels
- **Search** — Use `conversation_search(query)` for all platforms, or `search_channel(query, "discord")` for a specific one
- **Dashboard** — Stream stats show the new platform automatically; unknown platforms get a neutral color tag
- **RRF hybrid search** — Works across all platforms, no configuration needed

### Semantic search (optional)

```bash
ollama pull bge-m3 && ollama serve
```

Without this, keyword search still works — you just don't get vector similarity.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `IMPRINT_DATA_DIR` | project root | Directory for memory.db and files |
| `TZ_OFFSET` | `0` | UTC offset (e.g. `12`, `-5`) |
| `HEARTBEAT_INTERVAL` | `900` | Heartbeat interval (seconds) |
| `TELEGRAM_BOT_TOKEN` | — | From @BotFather |
| `TELEGRAM_CHAT_ID` | — | From @userinfobot |
| `QUIET_START` / `QUIET_END` | `23` / `7` | No proactive messages during these hours |

See [imprint-memory](https://github.com/Qizhan7/imprint-memory) for memory-specific config (embedding provider, model, etc).

## Customizing your Claude

The system is shaped by a few Markdown files. See **[docs/customization.md](docs/customization.md)** for the full guide.

The short version:

| File | What it does | Who writes it |
|------|-------------|---------------|
| `~/.claude/CLAUDE.md` | Personality, preferences, rules — the brain | You |
| `HEARTBEAT.md` | Heartbeat behavior + checklist | You |
| `memory/bank/*.md` | Structured knowledge (preferences, experience, relationships) | You + Claude |
| `MEMORY.md` | Auto-generated memory index | System |
| `memory/YYYY-MM-DD.md` | Daily logs | System |

## Acknowledgements

[imprint-memory](https://github.com/Qizhan7/imprint-memory) · [Anthropic](https://anthropic.com) · [Ollama](https://ollama.com) + [bge-m3](https://huggingface.co/BAAI/bge-m3)

## License

[MIT](LICENSE)
