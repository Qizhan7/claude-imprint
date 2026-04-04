#!/bin/bash
# Post-Response Hook (Stop event)
# Fires after every Claude response.
# Reads new messages from session .jsonl, writes to conversation_log,
# and regenerates recent_context.md for cross-channel awareness.
#
# stdin: JSON with session_id, transcript_path

INPUT=$(cat)
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# Parse stdin
TRANSCRIPT=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)

if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
    exit 0
fi

# Run the Python processor
python3 "$SCRIPT_DIR/hooks/post_response_processor.py" "$TRANSCRIPT" "$SESSION_ID" "$SCRIPT_DIR" 2>> "$LOG_DIR/post-response.log"

# Sync recent_context.md → CLAUDE.md AUTO section
python3 "$SCRIPT_DIR/update_claude_md.py" 2>> "$LOG_DIR/post-response.log" || true

# Check if recent_context.md needs compression (>120 message lines)
CONTEXT_FILE="$SCRIPT_DIR/recent_context.md"
if [ -f "$CONTEXT_FILE" ]; then
    MSG_LINES=$(grep -c '^\[' "$CONTEXT_FILE" 2>/dev/null || echo 0)
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
