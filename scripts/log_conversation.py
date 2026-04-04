#!/usr/bin/env python3
"""
Write a conversation_log entry via Python (not raw sqlite3 CLI).
Called from cron-task.sh to:
  1. Use parameterized queries (no SQL injection)
  2. Trigger FTS5 indexing with segment_cjk (CJK search support)

Usage:
  python3 scripts/log_conversation.py \
    --platform telegram --direction out --speaker Bot \
    --content "message content" --session "cron-heartbeat" --entrypoint cron
"""

import argparse
import os
import sys
from pathlib import Path

# Try to import from pip-installed package first, then local
try:
    from imprint_memory.db import _get_db, now_str
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from imprint_memory.db import _get_db, now_str


def main():
    parser = argparse.ArgumentParser(description="Log a conversation entry")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--direction", required=True, choices=["in", "out"])
    parser.add_argument("--speaker", required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument("--session", default="")
    parser.add_argument("--entrypoint", default="cron")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    ts = args.created_at or now_str()

    db = _get_db()
    db.execute(
        """INSERT INTO conversation_log
           (platform, direction, speaker, content, session_id, entrypoint, created_at, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (args.platform, args.direction, args.speaker,
         args.content, args.session, args.entrypoint, ts, args.summary),
    )
    db.commit()
    db.close()
    print(f"Logged: [{args.platform}/{args.direction}] {args.content[:50]}")


if __name__ == "__main__":
    main()
