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
echo "   Stop: ./stop.sh or kill \$(cat .pid-heartbeat)"
echo ""

mkdir -p logs data

if command -v caffeinate &>/dev/null; then
    echo "   Sleep prevention: caffeinate enabled"
    nohup caffeinate -i python3 -u agent.py >> logs/agent.log 2>&1 &
else
    echo "   Sleep prevention: caffeinate not found, starting without it"
    nohup python3 -u agent.py >> logs/agent.log 2>&1 &
fi
echo $! > .pid-heartbeat

echo "Agent started (PID: $(cat .pid-heartbeat))"
echo "   View logs: tail -f logs/agent.log"
