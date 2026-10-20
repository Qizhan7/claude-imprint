#!/bin/bash
# Post-Response Hook (Stop event)
# Fires after every Claude response.
# Reads new messages from session .jsonl, writes to conversation_log,
# and regenerates recent_context.md for cross-channel awareness.
#
# stdin: JSON with session_id, transcript_path

# Our own one-shot `claude -p` calls (starlog) must not log themselves.
[ -n "${IMPRINT_STARLOG_CHILD:-}" ] && exit 0

INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Use the project venv if there is one (Claude Code runs hooks with your login PATH).
[ -x "${IMPRINT_VENV:-$SCRIPT_DIR/.venv}/bin/python3" ] && export PATH="${IMPRINT_VENV:-$SCRIPT_DIR/.venv}/bin:$PATH"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Parse stdin
TRANSCRIPT=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)
HOOK_CWD=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null)

if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
    exit 0
fi

# Same data dir as the imprint-memory MCP server (default ~/.imprint), so
# logged turns show up in conversation_search. Set IMPRINT_DATA_DIR to override.
export IMPRINT_DATA_DIR="${IMPRINT_DATA_DIR:-$HOME/.imprint}"

# Run the Python processor
python3 "$SCRIPT_DIR/hooks/post_response_processor.py" "$TRANSCRIPT" "$SESSION_ID" "$SCRIPT_DIR" 2>> "$LOG_DIR/post-response.log"

# Starlog: maybe write one timeline line for this stretch of conversation.
# Detached so the hook returns immediately (it may call a small model).
if [ -f "$SCRIPT_DIR/packages/imprint_starlog/starlog.py" ] && [ "${STARLOG_DISABLE:-}" != "1" ]; then
    nohup python3 "$SCRIPT_DIR/packages/imprint_starlog/starlog.py" record "$TRANSCRIPT" "$SESSION_ID" "$HOOK_CWD" \
        >> "$LOG_DIR/starlog.log" 2>&1 < /dev/null &
fi

# Sync recent_context.md → CLAUDE.md AUTO section
python3 "$SCRIPT_DIR/update_claude_md.py" 2>> "$LOG_DIR/post-response.log" || true

# Check if recent_context.md needs compression (>120 message lines)
CONTEXT_FILE="$SCRIPT_DIR/recent_context.md"
if [ -f "$CONTEXT_FILE" ]; then
    MSG_LINES=$(grep -c '^\[' "$CONTEXT_FILE" 2>/dev/null) || MSG_LINES=0
    if [ "$MSG_LINES" -gt 120 ]; then
        if [ -f "$SCRIPT_DIR/scripts/compress_context.py" ]; then
            # Run compression in background to not block the hook
            nohup python3 "$SCRIPT_DIR/scripts/compress_context.py" "$CONTEXT_FILE" >> "$LOG_DIR/compress.log" 2>&1 &
        else
            # Fallback: simple tail trimming
            TMPFILE=$(mktemp)
            tail -60 "$CONTEXT_FILE" > "$TMPFILE" && mv "$TMPFILE" "$CONTEXT_FILE"
        fi
    fi
fi

exit 0
