# Claude Imprint

A self-hosted system that gives Claude persistent memory, multi-channel messaging, and automation. Talk to it from Claude Code, Claude.ai, Telegram, or WeChat — it remembers everything and shares context across channels.

Built for **Claude Code Pro/Max subscribers**. Uses only official Claude Code features — no API costs, no third-party auth.

## Features

**Memory** — SQLite + FTS5 + vector embeddings with RRF hybrid search, CJK support, categorized storage, knowledge bank, daily logs. Replaces Claude Code's built-in memory with something much more capable.

**Multi-channel** — Telegram, WeChat, Claude.ai, Claude Code. Each channel is independent and optional. They all share the same memory and context.

**Remote control** — From Claude.ai chat: run code on your machine, send Telegram messages, check system status, read webpages, control Spotify.

**Automation** — Scheduled tasks, heartbeat agent with proactive notifications, cron prompt templates for morning briefings / reminders / nightly cleanup.

**Dashboard** — FastAPI control panel (localhost:3000). Service manager, memory browser, interaction heatmap, conversation stream stats, scheduled tasks.

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

### WeChat

```bash
npm install -g claude-wechat-channel
claude --permission-mode auto --dangerously-load-development-channels server:wechat
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

[imprint-memory](https://github.com/Qizhan7/imprint-memory) · [Anthropic](https://anthropic.com) · [claude-wechat-channel](https://www.npmjs.com/package/claude-wechat-channel) · [Ollama](https://ollama.com) + [bge-m3](https://huggingface.co/BAAI/bge-m3)

## License

[MIT](LICENSE)
