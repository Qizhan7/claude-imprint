#!/bin/bash
# Claude Imprint — Stop heartbeat agent

cd "$(dirname "$0")"

if [ -f .pid ]; then
    PID=$(cat .pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm .pid
        echo "Agent stopped (PID: $PID)"
    else
        rm .pid
        echo "Process already gone, cleaned up PID file"
    fi
else
    echo "No running agent found"
fi
