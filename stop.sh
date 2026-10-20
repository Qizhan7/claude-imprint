#!/bin/bash
# Claude Imprint — Stop all services
# Works on both macOS and Linux/cloud servers.

cd "$(dirname "$0")"
echo "Stopping Claude Imprint..."

stop_pid() {
    local name="$1" pidfile="$2"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "   ✓ $name stopped (PID: $pid)"
        else
            echo "   - $name not running"
        fi
        rm -f "$pidfile"
    fi
}

stop_pid "Memory HTTP"  .pid-http
stop_pid "Tunnel"       .pid-tunnel
stop_pid "Heartbeat"    .pid-heartbeat
stop_pid "Dashboard"    .pid-dashboard
stop_pid "Telegram"     .pid-telegram

# Cleanup: kill any orphan processes
pkill -f "imprint-memory --http" 2>/dev/null || true
pkill -f "cloudflared tunnel run my-tunnel" 2>/dev/null || true  # only ours, not every tunnel on the machine

TG_SESSION="${HEARTBEAT_TMUX_TARGET:-imprint-tg}"
if command -v tmux &>/dev/null && tmux has-session -t "$TG_SESSION" 2>/dev/null; then
    tmux kill-session -t "$TG_SESSION" && echo "   ✓ Telegram (tmux $TG_SESSION) stopped"
elif [[ "$(uname)" == "Darwin" ]]; then
    echo ""
    echo "   Note: a Telegram Terminal window (started without tmux) has to be closed manually (Ctrl+C)"
else
    pkill -f "channels plugin:telegram" 2>/dev/null || true
fi

echo ""
echo "Done"
