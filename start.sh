#!/bin/bash
# Claude Imprint — Start all services
# Works on both macOS and Linux/cloud servers.
# Automatically skips components that are not configured or already running.

set -euo pipefail
cd "$(dirname "$0")"
mkdir -p logs

IS_MAC=false
[[ "$(uname)" == "Darwin" ]] && IS_MAC=true

is_running() {
    [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null
}

is_proc_running() {
    pgrep -f "$1" > /dev/null 2>&1
}

echo "Starting Claude Imprint... ($(date '+%Y-%m-%d %H:%M'))"
echo "Platform: $(uname -s)"
echo "========================================"

# ─── 1. Memory HTTP service ───
if is_running .pid-http; then
    echo "   ✓ Memory HTTP already running"
elif [ ! -f "${IMPRINT_OAUTH_FILE:-$HOME/.imprint-oauth.json}" ] && [ -z "${OAUTH_ACCESS_TOKEN:-}" ]; then
    echo "   - Memory HTTP: no credentials, skip (run: python3 scripts/generate_oauth.py)"
else
    echo "   Starting Memory HTTP..."
    nohup imprint-memory --http > logs/http.log 2>&1 &
    echo $! > .pid-http
    sleep 2
    echo "   ✓ Memory HTTP started (PID: $!, port 8000)"
fi

# ─── 2. Cloudflare Tunnel ───
if ! is_running .pid-http; then
    echo "   - Tunnel: Memory HTTP not running, skip"
elif ! command -v cloudflared &>/dev/null; then
    echo "   - Tunnel: cloudflared not installed, skip"
elif is_running .pid-tunnel; then
    echo "   ✓ Tunnel already running"
else
    echo "   Starting Cloudflare Tunnel..."
    nohup cloudflared tunnel run my-tunnel > logs/tunnel.log 2>&1 &
    echo $! > .pid-tunnel
    sleep 3
    echo "   ✓ Tunnel started"
fi

# ─── 3. Telegram ───
# Runs inside tmux so the heartbeat can paste pulses into this same session
# (see packages/imprint_heartbeat/heartbeat.py). Attach to watch it.
TG_SESSION="${HEARTBEAT_TMUX_TARGET:-imprint-tg}"
TG_CMD="claude --permission-mode auto --channels plugin:telegram@claude-plugins-official"
if command -v tmux &>/dev/null && tmux has-session -t "$TG_SESSION" 2>/dev/null; then
    echo "   ✓ Telegram already running (tmux attach -t $TG_SESSION)"
elif is_proc_running "channels plugin:telegram"; then
    echo "   ✓ Telegram already running (outside tmux: heartbeat falls back to headless mode)"
elif ! command -v claude &>/dev/null; then
    echo "   - Telegram: claude CLI not found, skip"
elif command -v tmux &>/dev/null; then
    echo "   Starting Telegram in tmux..."
    tmux new-session -d -s "$TG_SESSION" -c "$(pwd)" "$TG_CMD"
    echo "   ✓ Telegram started (watch: tmux attach -t $TG_SESSION, detach: Ctrl-b d)"
else
    echo "   Starting Telegram (no tmux: heartbeat will use headless mode)..."
    if $IS_MAC; then
        osascript -e 'tell application "Terminal" to do script "cd '"$(pwd)"' && '"$TG_CMD"'"' 2>/dev/null
        echo "   ✓ Telegram window opened"
    else
        echo "   ! Without tmux there's no terminal for an interactive session on Linux."
        echo "     Install tmux (apt install tmux) and run ./start.sh again."
    fi
fi

# ─── 4. Heartbeat ───
if is_running .pid-heartbeat; then
    echo "   ✓ Heartbeat already running"
elif [ -f packages/imprint_heartbeat/agent.py ]; then
    echo "   Starting Heartbeat Agent..."
    if $IS_MAC && command -v caffeinate &>/dev/null; then
        nohup caffeinate -i python3 -u packages/imprint_heartbeat/agent.py > logs/agent.log 2>&1 &
    else
        nohup python3 -u packages/imprint_heartbeat/agent.py > logs/agent.log 2>&1 &
    fi
    echo $! > .pid-heartbeat
    echo "   ✓ Heartbeat started (PID: $!, interval: ${HEARTBEAT_INTERVAL:-900}s)"
fi

# ─── 5. Dashboard ───
if is_proc_running "imprint_dashboard/dashboard.py"; then
    echo "   ✓ Dashboard already running"
elif [ -f packages/imprint_dashboard/dashboard.py ]; then
    echo "   Starting Dashboard..."
    nohup python3 packages/imprint_dashboard/dashboard.py > logs/dashboard.log 2>&1 &
    echo $! > .pid-dashboard
    sleep 1
    echo "   ✓ Dashboard started (PID: $!, http://localhost:3000)"
fi

echo ""
echo "========================================"
echo "Claude Imprint is running!"
echo "   Dashboard:  http://localhost:3000"
echo "   Memory API: http://localhost:8000/mcp"
echo "   Stop all:   ./stop.sh"
echo "   Logs:       logs/"
