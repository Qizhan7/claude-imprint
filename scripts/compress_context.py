#!/usr/bin/env python3
"""
Compress recent_context.md when it grows too large.
Thin wrapper so the post-response hook doesn't need to know implementation details.

Usage:
  python3 scripts/compress_context.py <context-file-path>

If imprint_memory.compress is available, delegates to it.
Otherwise falls back to simple tail truncation (keep last 60 lines).
"""

import sys
from pathlib import Path


def compress_simple(filepath: Path, keep_lines: int = 60):
    """Fallback: keep only the last N lines."""
    lines = filepath.read_text(encoding="utf-8").splitlines()
    if len(lines) <= keep_lines:
        return  # nothing to compress
    trimmed = lines[-keep_lines:]
    filepath.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
    print(f"Compressed {len(lines)} -> {len(trimmed)} lines (simple tail)")


def main():
    if len(sys.argv) < 2:
        print("Usage: compress_context.py <context-file>", file=sys.stderr)
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"File not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    # Try the full compression from imprint_memory package
    try:
        from imprint_memory.compress import compress_context
        compress_context(str(filepath))
        print(f"Compressed via imprint_memory.compress")
    except (ImportError, AttributeError):
        # Package not available or doesn't have compress module yet
        compress_simple(filepath)


if __name__ == "__main__":
    main()
