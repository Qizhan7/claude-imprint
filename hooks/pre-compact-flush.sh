#!/bin/bash
# Pre-Compaction Memory Flush
# Triggered automatically before CC compresses context.
# Reads the transcript and saves recent conversation to daily log.
# stdin: JSON with session_id, transcript_path, trigger

INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null)
TRIGGER=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('trigger','unknown'))" 2>/dev/null)
SESSION_ID=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null)

# Use system timezone by default; override with TZ env var if needed
DATE=$(date +%Y-%m-%d)
TIME=$(date +%H:%M)
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "$DATE $TIME PreCompact trigger=$TRIGGER session=$SESSION_ID" >> "$LOG_DIR/compaction.log"

if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ]; then
    python3.12 - "$TRANSCRIPT" "$DATE" "$TIME" "$TRIGGER" "$SCRIPT_DIR" << 'PYTHON_SCRIPT'
import sys
import json
from pathlib import Path

transcript_path = sys.argv[1]
date = sys.argv[2]
time_str = sys.argv[3]
trigger = sys.argv[4]
project_dir = sys.argv[5]

sys.path.insert(0, project_dir)

try:
    from memory_manager import remember, daily_log

    lines = []
    with open(transcript_path, 'r', encoding='utf-8') as f:
        for line in f:
            lines.append(line.strip())
    recent = lines[-50:] if len(lines) > 50 else lines

    messages = []
    for line in recent:
        try:
            entry = json.loads(line)
            role = entry.get("type", "")
            if role not in ("user", "assistant"):
                continue
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 10:
                messages.append(f"[{role}] {content[:200]}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if len(text) > 10:
                            messages.append(f"[{role}] {text[:200]}")
                            break
        except (json.JSONDecodeError, KeyError):
            continue

    if messages:
        summary_msgs = messages[-10:]
        summary = "\n".join(summary_msgs)
        daily_log(f"[{time_str}] Compaction ({trigger}). Recent conversation:\n{summary}")
        print(f"Extracted {len(summary_msgs)} messages to log", file=sys.stderr)
    else:
        daily_log(f"[{time_str}] Compaction ({trigger}). No extractable content.")
        print("No extractable messages", file=sys.stderr)

except Exception as e:
    print(f"Memory extraction failed: {e}", file=sys.stderr)
    try:
        from memory_manager import daily_log
        daily_log(f"[{time_str}] Compaction ({trigger}). Extraction failed: {e}")
    except:
        pass
PYTHON_SCRIPT
fi

exit 0
