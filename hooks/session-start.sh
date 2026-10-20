#!/bin/bash
# SessionStart hook: hand the new session today's starlog (what every window
# did today, arranged into short paragraphs + the newest raw lines).
# Whatever this prints is added to the session's context.
[ -n "${IMPRINT_STARLOG_CHILD:-}" ] && exit 0
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
[ -x "${IMPRINT_VENV:-$SCRIPT_DIR/.venv}/bin/python3" ] && export PATH="${IMPRINT_VENV:-$SCRIPT_DIR/.venv}/bin:$PATH"
export IMPRINT_DATA_DIR="${IMPRINT_DATA_DIR:-$HOME/.imprint}"
python3 "$SCRIPT_DIR/packages/imprint_starlog/starlog.py" context 2>/dev/null || true
exit 0
