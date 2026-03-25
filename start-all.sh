#!/bin/bash
# Claude Imprint — Start all services
# Skips components that are already running

cd "$(dirname "$0")"
mkdir -p logs

is_running() {
    [ -f "$1" ] && kill -0 $(cat "$1") 2>/dev/null
}

echo "✨ Starting Claude Imprint... ($(date '+%Y-%m-%d %H:%M'))"
echo "========================================"

# 1. Memory HTTP service
if is_running .pid-http; then
    echo "   🧠 Memory HTTP already running, skip"
else
    echo "🧠 Starting Memory HTTP..."
    python3.12 -u memory_mcp.py --http > logs/http.log 2>&1 &
    echo $! > .pid-http
    sleep 2
    echo "   ✅ Memory HTTP (PID: $!, port 8000)"
fi

# 2. Cloudflare Tunnel (edit tunnel name below)
if is_running .pid-tunnel; then
    echo "   🌐 Tunnel already running, skip"
else
    echo "🌐 Starting Cloudflare Tunnel..."
    cloudflared tunnel run my-tunnel > logs/tunnel.log 2>&1 &
    echo $! > .pid-tunnel
    sleep 5
    echo "   ✅ Tunnel started"
fi

# 3. Telegram (opens new terminal window — macOS)
if pgrep -f "channels plugin:telegram" > /dev/null 2>&1; then
    echo "   📨 Telegram already running, skip"
else
    echo "📨 Starting Telegram..."
    osascript -e 'tell application "Terminal" to do script "claude --channels plugin:telegram@claude-plugins-official"' 2>/dev/null
    echo "   ✅ Telegram window opened"
fi

# 4. WeChat (opens new terminal window — macOS)
if pgrep -f "dangerously-load-development-channels server:wechat" > /dev/null 2>&1; then
    echo "   📱 WeChat already running, skip"
else
    echo "📱 Starting WeChat..."
    osascript -e 'tell application "Terminal" to do script "claude --dangerously-load-development-channels server:wechat"' 2>/dev/null
    echo "   ✅ WeChat window opened"
fi

echo ""
echo "========================================"
echo "✨ Claude Imprint is running!"
echo "   Dashboard: python3.12 dashboard.py → http://localhost:3000"
echo "   Stop all:  ./stop-all.sh"
