#!/usr/bin/env python3.12
"""
Claude.ai Chat History Cleaner

Usage:
  1. Export data from Claude.ai (Settings > Privacy > Export Data)
  2. Unzip the export, find conversations.json
  3. Run: python3.12 chat_cleaner.py <path to conversations.json>

Features:
  - Parses conversations.json
  - Splits into sessions by 6-hour silence gaps
  - Long sessions (>50k chars) get secondary splits with 2k overlap
  - Each session becomes a separate file for feeding to CC for memory extraction
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ─── Config ──────────────────────────────────────────────
GAP_HOURS = 6           # Silence gap threshold (hours)
MAX_CHARS = 50000       # Max chars per chunk
OVERLAP_CHARS = 2000    # Context overlap for secondary splits
OUTPUT_DIR = Path(__file__).parent / "chat_sessions"


def parse_conversations(path: str) -> list[dict]:
    """Parse conversations.json"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = []
    items = data if isinstance(data, list) else data.get("conversations", data.get("data", [data]))

    for conv in items:
        messages = []
        raw_msgs = conv.get("chat_messages", conv.get("messages", []))
        title = conv.get("name", conv.get("title", ""))
        conv_id = conv.get("uuid", conv.get("id", ""))

        for msg in raw_msgs:
            role = msg.get("sender", msg.get("role", ""))
            if role in ("human", "user"):
                role = "User"
            elif role in ("assistant",):
                role = "Assistant"

            text = ""
            content = msg.get("content", msg.get("text", ""))
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        parts.append(part)
                text = "\n".join(parts)

            if not text.strip():
                continue

            ts_raw = msg.get("created_at", msg.get("timestamp", ""))
            ts = None
            if ts_raw:
                try:
                    if isinstance(ts_raw, (int, float)):
                        ts = datetime.fromtimestamp(ts_raw)
                    else:
                        for fmt in [
                            "%Y-%m-%dT%H:%M:%S.%fZ",
                            "%Y-%m-%dT%H:%M:%SZ",
                            "%Y-%m-%dT%H:%M:%S.%f%z",
                            "%Y-%m-%dT%H:%M:%S%z",
                        ]:
                            try:
                                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                                break
                            except Exception:
                                try:
                                    ts = datetime.strptime(ts_raw, fmt)
                                    break
                                except Exception:
                                    continue
                except Exception:
                    pass

            messages.append({
                "role": role,
                "text": text,
                "ts": ts,
                "conv_title": title,
                "conv_id": conv_id,
            })

        if messages:
            conversations.append(messages)

    return conversations


def split_by_gap(conversations: list[list[dict]], gap_hours: int = GAP_HOURS) -> list[list[dict]]:
    """Split conversations into sessions by silence gaps."""
    sessions = []

    for conv_msgs in conversations:
        sorted_msgs = sorted(conv_msgs, key=lambda m: m["ts"] or datetime.min)

        current_session = []
        for msg in sorted_msgs:
            if current_session and msg["ts"] and current_session[-1]["ts"]:
                gap = msg["ts"] - current_session[-1]["ts"]
                if gap > timedelta(hours=gap_hours):
                    sessions.append(current_session)
                    current_session = []
            current_session.append(msg)

        if current_session:
            sessions.append(current_session)

    sessions.sort(key=lambda s: s[0]["ts"] or datetime.min)
    return sessions


def format_session(messages: list[dict]) -> str:
    """Format a session as readable text"""
    lines = []
    title = messages[0].get("conv_title", "")
    if title:
        lines.append(f"# {title}")
        lines.append("")

    first_ts = messages[0].get("ts")
    if first_ts:
        lines.append(f"Date: {first_ts.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")

    for msg in messages:
        ts_str = msg["ts"].strftime("%H:%M") if msg["ts"] else ""
        lines.append(f"**{msg['role']}** [{ts_str}]:")
        lines.append(msg["text"])
        lines.append("")

    return "\n".join(lines)


def split_long_session(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split long sessions by character count with overlap"""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end < len(text):
            newline_pos = text.rfind("\n", start + max_chars - 5000, end)
            if newline_pos > start:
                end = newline_pos

        chunk = text[start:end]
        if chunks:
            chunk = f"[...continued from above...]\n\n{chunk}"
        if end < len(text):
            chunk += "\n\n[...continues below...]"

        chunks.append(chunk)
        start = end - overlap

    return chunks


def main():
    if len(sys.argv) < 2:
        print("Usage: python3.12 chat_cleaner.py <path to conversations.json>")
        print()
        print("Example: python3.12 chat_cleaner.py ~/Downloads/claude-export/conversations.json")
        sys.exit(1)

    input_path = sys.argv[1]
    if not Path(input_path).exists():
        print(f"File not found: {input_path}")
        sys.exit(1)

    print(f"Reading {input_path}...")
    conversations = parse_conversations(input_path)
    total_msgs = sum(len(c) for c in conversations)
    print(f"  Found {len(conversations)} conversations, {total_msgs} messages")

    print(f"Splitting by {GAP_HOURS}-hour gaps...")
    sessions = split_by_gap(conversations)
    print(f"  Split into {len(sessions)} sessions")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    chunk_count = 0
    stats = {"sessions": len(sessions), "chunks": 0, "skipped": 0}

    for i, session in enumerate(sessions):
        text = format_session(session)

        if len(text) < 200:
            stats["skipped"] += 1
            continue

        chunks = split_long_session(text)
        ts_str = session[0]["ts"].strftime("%Y%m%d_%H%M") if session[0].get("ts") else f"unknown_{i}"

        for j, chunk in enumerate(chunks):
            chunk_count += 1
            suffix = f"_part{j+1}" if len(chunks) > 1 else ""
            filename = f"{ts_str}{suffix}.md"
            out_path = OUTPUT_DIR / filename
            out_path.write_text(chunk, encoding="utf-8")

        stats["chunks"] += len(chunks)

    # Write extraction prompt template
    prompt_path = OUTPUT_DIR / "_EXTRACT_PROMPT.md"
    prompt_path.write_text("""# Memory Extraction Prompt

Use in a new CC session. Feed one session file at a time with this prompt:

---

Read the following chat history and extract all information worth remembering long-term.
Use the memory_remember tool to save each piece.

What to extract:
- Preferences, habits, experiences, important events
- Important relationship moments, agreements
- Technical decisions, architecture changes
- People and relationships mentioned
- NOT: casual greetings, debugging sessions, temporary errors

For each memory, call memory_remember once. Use category: facts/events/experience, source: chat.
After extraction, tell me how many memories were saved from this session.

Chat history:
[paste session file content here]
""", encoding="utf-8")

    # Write batch processing script
    batch_path = OUTPUT_DIR / "_batch_extract.sh"
    batch_path.write_text(f"""#!/bin/bash
# Batch memory extraction (feed sessions to CC one by one)
# Usage: bash _batch_extract.sh

PROMPT=$(cat _EXTRACT_PROMPT.md | tail -n +7)
DIR="{OUTPUT_DIR}"

for f in "$DIR"/2*.md; do
    echo "Processing: $(basename $f)"
    CONTENT=$(cat "$f")
    claude -p "$PROMPT

Chat history:
$CONTENT" --allowedTools "mcp__imprint-memory__memory_remember" 2>/dev/null
    echo "  Done"
    echo ""
done

echo "All sessions processed!"
""", encoding="utf-8")
    batch_path.chmod(0o755)

    print()
    print(f"Done!")
    print(f"  Sessions: {stats['sessions']}")
    print(f"  Output files: {stats['chunks']}")
    print(f"  Skipped (too short): {stats['skipped']}")
    print(f"  Output directory: {OUTPUT_DIR}")
    print()
    print(f"Next steps:")
    print(f"  Option A (manual): Open new CC session, follow _EXTRACT_PROMPT.md")
    print(f"  Option B (auto):   bash {batch_path}")


if __name__ == "__main__":
    main()
