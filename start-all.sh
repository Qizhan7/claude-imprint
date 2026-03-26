#!/bin/bash
# Claude Imprint — Start all services
# Automatically skips components that are not configured or already running

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
    python3 -u memory_mcp.py --http > logs/http.log 2>&1 &
    echo $! > .pid-http
    sleep 2
    echo "   ✅ Memory HTTP (PID: $!, port 8000)"
fi

# 2. Cloudflare Tunnel (skip if cloudflared not installed)
if ! command -v cloudflared &>/dev/null; then
    echo "   🌐 Tunnel: cloudflared not installed, skip"
elif is_running .pid-tunnel; then
    echo "   🌐 Tunnel already running, skip"
else
    echo "🌐 Starting Cloudflare Tunnel..."
    cloudflared tunnel run my-tunnel > logs/tunnel.log 2>&1 &
    echo $! > .pid-tunnel
    sleep 5
    echo "   ✅ Tunnel started"
fi

# 3. Telegram (skip if plugin not available)
if pgrep -f "channels plugin:telegram" > /dev/null 2>&1; then
    echo "   📨 Telegram already running, skip"
elif ! command -v claude &>/dev/null; then
    echo "   📨 Telegram: claude not found, skip"
else
    echo "📨 Starting Telegram..."
    osascript -e 'tell application "Terminal" to do script "claude --permission-mode auto --channels plugin:telegram@claude-plugins-official"' 2>/dev/null
    echo "   ✅ Telegram window opened"
fi

# 4. WeChat (skip if not installed)
if pgrep -f "dangerously-load-development-channels server:wechat" > /dev/null 2>&1; then
    echo "   📱 WeChat already running, skip"
elif ! npm list -g claude-wechat-channel &>/dev/null 2>&1; then
    echo "   📱 WeChat: claude-wechat-channel not installed, skip"
else
    echo "📱 Starting WeChat..."
    osascript -e 'tell application "Terminal" to do script "claude --permission-mode auto --dangerously-load-development-channels server:wechat"' 2>/dev/null
    echo "   ✅ WeChat window opened"
fi

echo ""
echo "========================================"
echo "✨ Claude Imprint is running!"
echo "   Dashboard: python3 dashboard.py → http://localhost:3000"
echo "   Stop all:  ./stop-all.sh"
