#!/usr/bin/env python3
"""
Auto-update CLAUDE.md with recent memories and experience.
Designed to run as a scheduled task (e.g., daily after nightly consolidation).

Reads from:
  - memory.db (high-importance recent memories)
  - memory/bank/experience.md (latest experience entries)
  - memory/ daily logs (last 2 days)

Writes to:
  - ~/.claude/CLAUDE.md (replaces the ◆ AUTO section only)
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone

# --- Config ---
import os
TZ_OFFSET = int(os.environ.get("TZ_OFFSET", 0))
LOCAL_TZ = timezone(timedelta(hours=TZ_OFFSET))
PROJECT_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("IMPRINT_DATA_DIR", str(Path.home() / ".imprint")))
DB_PATH = DATA_DIR / "memory.db"
CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
EXPERIENCE_FILE = DATA_DIR / "memory/bank/experience.md"
DAILY_LOG_DIR = DATA_DIR / "memory"

AUTO_MARKER_START = "---\n## ◆ AUTO — 自动生成区域（脚本更新，勿手动编辑）"
AUTO_MARKER_END = "<!-- END AUTO -->"

# How many days of memories to include
RECENT_DAYS = 4
# Minimum importance to include
MIN_IMPORTANCE = 7
# Max items from memory.db
MAX_MEMORY_ITEMS = 10
# How many experience sections to include (from the end)
MAX_EXPERIENCE_SECTIONS = 2


def _now():
    return datetime.now(LOCAL_TZ)


def get_recent_memories():
    """Fetch high-importance recent memories from DB."""
    if not DB_PATH.exists():
        return []

    cutoff = (_now() - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    rows = db.execute("""
        SELECT content, category, importance, created_at
        FROM memories
        WHERE importance >= ? AND created_at >= ?
        ORDER BY importance DESC, created_at DESC
        LIMIT ?
    """, (MIN_IMPORTANCE, cutoff, MAX_MEMORY_ITEMS)).fetchall()

    db.close()
    return rows


def get_recent_experience():
    """Get section headers + recent entries from experience.md."""
    if not EXPERIENCE_FILE.exists():
        return ""

    text = EXPERIENCE_FILE.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Filter out comment-only lines
    content_lines = [l for l in lines if l.strip() and not l.strip().startswith("<!--")]

    # Only take ## headers and their bullet points (skip the title line)
    sections = []
    current_section = []
    for line in content_lines:
        if line.startswith("## "):
            if current_section:
                sections.append(current_section)
            current_section = [line]
        elif current_section:
            current_section.append(line)
    if current_section:
        sections.append(current_section)

    # Take only the most recent sections
    recent = sections[-MAX_EXPERIENCE_SECTIONS:] if len(sections) > MAX_EXPERIENCE_SECTIONS else sections
    return "\n".join(line for section in recent for line in section)


def get_recent_daily_logs():
    """Get last 2 days of daily logs, truncated to key events only."""
    today = _now().strftime("%Y-%m-%d")
    yesterday = (_now() - timedelta(days=1)).strftime("%Y-%m-%d")

    logs = []
    for date_str in [today, yesterday]:
        log_file = DAILY_LOG_DIR / f"{date_str}.md"
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8").strip().splitlines()
            # Keep header + bullet points only (skip compaction dumps)
            filtered = []
            skip_rest = False
            for line in lines:
                # Skip compaction auto-saves and everything after them
                if "Compaction (auto)" in line:
                    skip_rest = True
                    continue
                if skip_rest:
                    # Resume on next timestamped entry
                    if line.startswith("- [") and "]" in line[:8]:
                        skip_rest = False
                    else:
                        continue
                # Skip lines that are clearly raw transcript
                if line.startswith("[assistant]") or line.startswith("[user]"):
                    continue
                # Skip markdown tables and fragments from compaction dumps
                if line.startswith("|") or line.startswith("**") or line.strip() == "":
                    if not line.startswith("# "):
                        continue
                # Truncate long lines
                if len(line) > 200:
                    line = line[:200] + "..."
                filtered.append(line)
            if filtered:
                logs.append("\n".join(filtered))

    return "\n\n".join(logs)


def build_auto_section():
    """Build the AUTO section content."""
    tz_label = f"UTC{'+' if TZ_OFFSET >= 0 else ''}{TZ_OFFSET}"
    now_str = _now().strftime(f"%Y-%m-%d %H:%M {tz_label}")
    parts = [
        AUTO_MARKER_START,
        f"最后更新：{now_str}\n",
    ]

    # Cross-channel recent context
    context_file = PROJECT_DIR / "recent_context.md"
    if context_file.exists():
        context_text = context_file.read_text(encoding="utf-8").strip()
        # Strip HTML comments
        context_lines = [l for l in context_text.splitlines() if not l.startswith("<!--")]
        if context_lines:
            # 提取最后一条用户发的消息，放在最醒目的位置
            last_inbound = None
            for line in reversed(context_lines):
                if "/in]" in line:
                    last_inbound = line.strip()
                    break
            if last_inbound:
                # Map platform abbreviations to display names
                PLATFORM_NAMES = {
                    "wx": "WeChat",
                    "tg": "Telegram",
                    "dc": "Discord",
                    "sl": "Slack",
                }
                platform = "unknown"
                for abbr, name in PLATFORM_NAMES.items():
                    if f"{abbr}/" in last_inbound:
                        platform = name
                        break
                parts.append(f"### ⚡ 最近一次跨渠道互动")
                parts.append(f"来自{platform}：{last_inbound}")
                parts.append(f"↑ 如果你现在在另一个渠道，注意这条消息的上下文。用户可能刚从那边过来。")
                parts.append("")

            parts.append("### 近期跨渠道上下文")
            parts.append("\n".join(context_lines[-30:]))  # last 30 lines
            parts.append("")

    # Recent memories
    memories = get_recent_memories()
    if memories:
        parts.append("### 近期重要记忆")
        for m in memories:
            date = m["created_at"][:10]
            cat = m["category"]
            # Truncate long content
            content = m["content"]
            if len(content) > 150:
                content = content[:150] + "..."
            parts.append(f"- [{cat}][{date}] {content}")
        parts.append("")

    # Experience summary removed from AUTO to save tokens
    # Available at memory/bank/experience.md when needed

    # Daily logs removed from AUTO to save tokens
    # Available at memory/YYYY-MM-DD.md when needed

    parts.append(AUTO_MARKER_END)
    return "\n".join(parts)


def update_claude_md():
    """Update CLAUDE.md, replacing only the AUTO section."""
    if not CLAUDE_MD.exists():
        print(f"CLAUDE.md not found at {CLAUDE_MD}")
        return

    content = CLAUDE_MD.read_text(encoding="utf-8")
    auto_section = build_auto_section()

    # Find and replace existing AUTO section
    start_idx = content.find("## ◆ AUTO")
    if start_idx != -1:
        # Find the --- before it
        dash_idx = content.rfind("---", 0, start_idx)
        if dash_idx != -1:
            start_idx = dash_idx

        end_idx = content.find(AUTO_MARKER_END)
        if end_idx != -1:
            end_idx += len(AUTO_MARKER_END)
            content = content[:start_idx].rstrip() + "\n\n" + auto_section + "\n"
        else:
            # No end marker, replace from start to end of file
            content = content[:start_idx].rstrip() + "\n\n" + auto_section + "\n"
    else:
        # First time: append to end
        content = content.rstrip() + "\n\n" + auto_section + "\n"

    CLAUDE_MD.write_text(content, encoding="utf-8")
    print(f"✅ CLAUDE.md AUTO section updated ({_now().strftime('%H:%M')})")
    print(f"   Memories: {len(get_recent_memories())} items")


if __name__ == "__main__":
    update_claude_md()
