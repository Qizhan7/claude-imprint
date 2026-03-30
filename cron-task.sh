#!/bin/bash
# ─── Imprint Cron Task Runner ───
# Runs a claude CLI task with north-memory MCP only (no telegram/wechat plugins).
# Usage: cron-task.sh <task-name> <prompt-file>
#
# Design decisions:
#   - Runs from $HOME to avoid loading claude-imprint/.mcp.json (has wechat)
#   - Uses cron-mcp.json with only north-memory
#   - Captures AI output; if telegram was sent, appends to recent_context.md
#   - --max-budget-usd caps cost; CLI exits naturally after completion

set -euo pipefail

TASK_NAME="${1:?Usage: cron-task.sh <task-name> <prompt-file>}"
PROMPT_FILE="${2:?Usage: cron-task.sh <task-name> <prompt-file>}"
PROJECT_DIR="$HOME/Desktop/claude-imprint"
LOG_DIR="$PROJECT_DIR/logs"
CONTEXT_FILE="$PROJECT_DIR/recent_context.md"
MCP_CONFIG="$PROJECT_DIR/cron-mcp.json"

# ─── Environment ───
# cron has a minimal PATH; set up everything we need
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/cron-${TASK_NAME}.log"

# ─── Timestamp ───
TS=$(TZ=Pacific/Auckland date +"%Y-%m-%d %H:%M")
TS_SHORT=$(TZ=Pacific/Auckland date +"%m-%d %H:%M")

echo "[$TS] === $TASK_NAME start ===" >> "$LOGFILE"

# ─── Read prompt ───
if [ ! -f "$PROMPT_FILE" ]; then
    echo "[$TS] ERROR: prompt file not found: $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi
PROMPT=$(cat "$PROMPT_FILE")

# ─── Run claude CLI ───
# Run from $HOME to avoid loading project-level .mcp.json (has wechat config)
TMPOUT=$(mktemp)
cd "$HOME"
claude -p "$PROMPT" \
    --mcp-config "$MCP_CONFIG" \
    --dangerously-skip-permissions \
    --max-budget-usd 0.50 \
    --output-format text \
    < /dev/null > "$TMPOUT" 2>> "$LOGFILE" || true

OUTPUT=$(cat "$TMPOUT")
rm -f "$TMPOUT"

echo "[$TS] Output: ${OUTPUT:0:200}" >> "$LOGFILE"

# ─── Append to recent_context.md if telegram was sent ───
# The AI output should contain a line like: SENT_TG: <message content>
# This is instructed in each task's prompt.
SENT_MSG=$(echo "$OUTPUT" | grep "^SENT_TG:" | head -1 | sed 's/^SENT_TG: *//')

if [ -n "$SENT_MSG" ]; then
    DISPLAY="${SENT_MSG:0:200}"

    # Write to conversation_log DB (source of truth — Stop hook rebuilds recent_context from this)
    DB_FILE="$PROJECT_DIR/memory.db"
    DB_TS=$(TZ=Pacific/Auckland date +"%Y-%m-%d %H:%M:%S")
    sqlite3 "$DB_FILE" "INSERT INTO conversation_log (platform, direction, speaker, content, session_id, entrypoint, created_at, summary) VALUES ('telegram', 'out', 'Agent', '${DISPLAY//\'/\'\'}', 'cron-${TASK_NAME}', 'cron', '${DB_TS}', '');" 2>> "$LOGFILE" || true

    # Also append to recent_context.md directly (in case Stop hook hasn't run yet)
    echo "[$TS_SHORT tg/out] $DISPLAY" >> "$CONTEXT_FILE"

    echo "[$TS] Logged to DB + appended to recent_context: $DISPLAY" >> "$LOGFILE"
fi

# Sync recent_context.md → CLAUDE.md AUTO section
# So telegram channel and other windows see the latest context
python3.12 "$PROJECT_DIR/update_claude_md.py" >> "$LOGFILE" 2>&1 || true

echo "[$TS] === $TASK_NAME done ===" >> "$LOGFILE"
