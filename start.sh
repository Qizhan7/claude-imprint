#!/bin/bash
# Claude Imprint — Start heartbeat agent
# Uses caffeinate to prevent Mac sleep

cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$HOME/.bun/bin:$PATH"

if ! command -v claude &>/dev/null; then
    echo "Error: claude CLI not found. Please install Claude Code first."
    exit 1
fi

echo "Starting Claude Imprint Agent..."
echo "   Heartbeat interval: ${HEARTBEAT_INTERVAL:-900}s"
echo "   Logs: ./logs/agent.log"
echo "   Stop: ./stop.sh or kill \$(cat .pid)"
echo ""

mkdir -p logs data

nohup caffeinate -i python3.12 -u agent.py >> logs/agent.log 2>&1 &
echo $! > .pid

echo "Agent started (PID: $(cat .pid))"
echo "   View logs: tail -f logs/agent.log"
