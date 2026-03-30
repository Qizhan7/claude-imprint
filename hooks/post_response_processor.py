#!/usr/bin/env python3
"""
Post-response processor: reads new .jsonl messages, writes to conversation_log,
and regenerates recent_context.md.

Called by post-response.sh with args: transcript_path session_id project_dir
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# Args
transcript_path = sys.argv[1]
session_id = sys.argv[2]
project_dir = sys.argv[3]

sys.path.insert(0, str(Path(project_dir) / "packages"))

from imprint_memory.conversation import log_message, get_recent, format_recent
from imprint_memory.db import now_str

# ─── Config ───────────────────────────────────────────────
OFFSET_DIR = Path(project_dir) / "logs"
OFFSET_DIR.mkdir(parents=True, exist_ok=True)
CONTEXT_FILE = Path(project_dir) / "recent_context.md"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
SUMMARIZE_MODEL = os.environ.get("COMPRESS_MODEL", "goekdenizguelmez/JOSIEFIED-Qwen3:8b")
SUMMARIZE_THRESHOLD = 50  # chars — messages longer than this get summarized

# Channel tag regex
CHANNEL_RE = re.compile(
    r'<channel\s+source="([^"]*)"[^>]*?'
    r'(?:ts="([^"]*)")?[^>]*?>\s*(.*?)\s*</channel>',
    re.DOTALL,
)


def summarize_text(text: str) -> str:
    """Call JOSIEFIED via Ollama to summarize a long message into one line.
    Returns empty string on failure (caller should fall back to truncation)."""
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps({
                "model": SUMMARIZE_MODEL,
                "messages": [
                    {"role": "system", "content": (
                        "你是对话日志压缩器。把下面的消息压缩成一句话摘要（中文）。"
                        "用第三人称。"
                        "保留关键信息（做了什么、讨论了什么、决定了什么）。"
                        "如果消息中有重要的原话，用引号保留。"
                        "只输出摘要，不要任何前缀或解释。"
                    )},
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.3, "num_predict": 100},
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        result = resp.get("message", {}).get("content", "").strip()
        # Clean up: take first line only, strip quotes
        if result:
            result = result.splitlines()[0].strip().strip('"\'')
        return result if result else ""
    except Exception as e:
        print(f"Ollama summarize failed: {e}", file=sys.stderr)
        return ""


def get_offset(session_id: str) -> int:
    """Get byte offset for this session."""
    marker = OFFSET_DIR / f".offset-{session_id}"
    if marker.exists():
        try:
            return int(marker.read_text().strip())
        except (ValueError, OSError):
            pass
    return 0


def set_offset(session_id: str, offset: int):
    """Save byte offset for this session."""
    marker = OFFSET_DIR / f".offset-{session_id}"
    marker.write_text(str(offset))


def extract_text(content) -> str:
    """Extract readable text from message content."""
    if isinstance(content, str):
        # Strip channel tags to get clean text
        m = CHANNEL_RE.search(content)
        if m:
            return m.group(3).strip()
        return content.strip()

    if isinstance(content, list):
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    texts.append(text)
        return "\n".join(texts)

    return ""


def parse_platform(entry: dict, content) -> str:
    """Determine platform from entry."""
    origin = entry.get("origin", {})
    if isinstance(origin, dict) and origin.get("kind") == "channel":
        server = origin.get("server", "")
        if "telegram" in server:
            return "telegram"
        if "wechat" in server:
            return "wechat"
        return "channel"

    # Check content for channel tags
    if isinstance(content, str):
        m = CHANNEL_RE.search(content)
        if m:
            source = m.group(1)
            if "telegram" in source:
                return "telegram"
            if "wechat" in source:
                return "wechat"

    entrypoint = entry.get("entrypoint", "")
    if entrypoint == "sdk-cli":
        return "heartbeat"
    return "cc"


def process_new_messages(transcript_path: str, session_id: str) -> int:
    """Read new messages from .jsonl, write to conversation_log. Returns count."""
    offset = get_offset(session_id)
    file_size = os.path.getsize(transcript_path)

    if offset >= file_size:
        return 0

    count = 0
    new_offset = offset

    with open(transcript_path, "rb") as f:
        f.seek(offset)
        while True:
            raw = f.readline()
            if not raw:
                break
            new_offset = f.tell()
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            if entry_type not in ("user", "assistant"):
                continue

            msg = entry.get("message", {})
            if not isinstance(msg, dict):
                continue

            content = msg.get("content", "")
            text = extract_text(content)
            if not text or len(text) < 3:
                continue

            # Skip very long messages (heartbeat prompts, system injections)
            if len(text) > 2000:
                text = text[:2000] + "..."

            platform = parse_platform(entry, content)
            direction = "in" if entry_type == "user" else "out"

            # Timestamp
            ts = entry.get("timestamp", "")
            if isinstance(ts, str) and ts:
                ts = ts[:19].replace("T", " ")
            elif isinstance(ts, (int, float)):
                from datetime import datetime
                ts = datetime.fromtimestamp(
                    ts / 1000 if ts > 1e12 else ts
                ).strftime("%Y-%m-%d %H:%M")
            else:
                ts = now_str()

            entrypoint = entry.get("entrypoint", "")

            # Per-message summarization: >50 chars → JOSIEFIED summary
            # Skip for CC platform — summaries are only used in recent_context.md
            # which excludes CC, so no point running Ollama for these
            summary = ""
            if platform not in ("cc", "heartbeat") and len(text) > SUMMARIZE_THRESHOLD:
                summary = summarize_text(text)

            log_message(
                platform=platform,
                direction=direction,
                content=text,
                session_id=session_id,
                entrypoint=entrypoint,
                created_at=ts,
                summary=summary,
            )
            count += 1

    set_offset(session_id, new_offset)
    return count


def regenerate_context():
    """Regenerate recent_context.md from cross-channel messages only.
    Excludes CC platform — CC has its own context/compaction mechanism."""
    messages = get_recent(exclude_platforms=["cc", "heartbeat"], limit=100)
    if not messages:
        # Write empty file so CLAUDE.md AUTO section doesn't show stale data
        messages = []

    header = (
        "<!-- Auto-generated by post-response hook. Do not edit. -->\n"
        f"<!-- Updated: {now_str()} NZST -->\n\n"
    )
    body = format_recent(messages)
    content = header + body + "\n"

    # Atomic write
    tmp = CONTEXT_FILE.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(CONTEXT_FILE))


def main():
    try:
        count = process_new_messages(transcript_path, session_id)
        if count > 0:
            regenerate_context()
            print(f"Processed {count} new messages, updated recent_context.md", file=sys.stderr)
    except Exception as e:
        print(f"post-response error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
