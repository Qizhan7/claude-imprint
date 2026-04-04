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
PROJECT_DIR="${IMPRINT_PROJECT_DIR:-$(cd "$(dirname "$0")" && pwd)}"
LOG_DIR="$PROJECT_DIR/logs"
CONTEXT_FILE="$PROJECT_DIR/recent_context.md"
MCP_CONFIG="$PROJECT_DIR/cron-mcp.json"

# ─── Environment ───
# cron has a minimal PATH; set up everything we need
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# ─── Auth ───
# Max Plan users: store your OAuth token in ~/.claude/cron-token
# API key users: store your key in ~/.claude/cron-token and uncomment ANTHROPIC_API_KEY
TOKEN_FILE="$HOME/.claude/cron-token"
if [ -f "$TOKEN_FILE" ]; then
    export CLAUDE_CODE_OAUTH_TOKEN=$(cat "$TOKEN_FILE")
    # export ANTHROPIC_API_KEY=$(cat "$TOKEN_FILE")  # uncomment for API key auth
fi

mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/cron-${TASK_NAME}.log"

# ─── Timestamp ───
TS=$(date +"%Y-%m-%d %H:%M")
TS_SHORT=$(date +"%m-%d %H:%M")

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

    # Write to conversation_log via Python (parameterized query + FTS5 CJK trigger)
    DB_TS=$(date +"%Y-%m-%d %H:%M:%S")
    python3 "$PROJECT_DIR/scripts/log_conversation.py" \
        --platform telegram --direction out --speaker Agent \
        --content "$DISPLAY" --session "cron-${TASK_NAME}" --entrypoint cron \
        --created-at "$DB_TS" 2>> "$LOGFILE" || true

    # Also append to recent_context.md directly (in case Stop hook hasn't run yet)
    echo "[$TS_SHORT tg/out] $DISPLAY" >> "$CONTEXT_FILE"

    echo "[$TS] Logged to DB + appended to recent_context: $DISPLAY" >> "$LOGFILE"
fi

# Sync recent_context.md → CLAUDE.md AUTO section
# So telegram channel and other windows see the latest context
python3 "$PROJECT_DIR/update_claude_md.py" >> "$LOGFILE" 2>&1 || true

echo "[$TS] === $TASK_NAME done ===" >> "$LOGFILE"
