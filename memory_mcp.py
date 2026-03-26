#!/usr/bin/env python3
"""
Claude Imprint — Memory MCP Server (FastMCP)
Exposes memory operations as MCP tools for all Claude Code sessions.

Usage:
  python3 memory_mcp.py           # stdio mode (for CC local use)
  python3 memory_mcp.py --http    # HTTP mode (for Claude.ai via tunnel)
"""

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

# Load Telegram env vars from .env file
_tg_env = Path.home() / ".claude" / "channels" / "telegram" / ".env"
if _tg_env.exists():
    for _line in _tg_env.read_text().splitlines():
        _line = _line.strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            if not os.environ.get(_k):
                os.environ[_k] = _v.strip()

from mcp.server.fastmcp import FastMCP
import memory_manager as mem

is_http = "--http" in sys.argv

mcp = FastMCP(
    "imprint-memory",
    host="0.0.0.0" if is_http else "127.0.0.1",
    port=8000,
)


@mcp.tool()
def memory_remember(content: str, category: str = "general", source: str = "cc", importance: int = 5) -> str:
    """Store a memory. Call this when you encounter important information.
    category: facts/events/tasks/experience/general
    source: cc/telegram/wechat/chat"""
    return mem.remember(content=content, category=category, source=source, importance=importance)


@mcp.tool()
def memory_search(query: str, limit: int = 10) -> str:
    """Search memories. Supports semantic search (natural language)."""
    return mem.search_text(query=query, limit=limit)


@mcp.tool()
def memory_forget(keyword: str) -> str:
    """Delete memories containing the specified keyword."""
    return mem.forget(keyword=keyword)


@mcp.tool()
def memory_daily_log(text: str) -> str:
    """Append to today's daily log."""
    return mem.daily_log(text=text)


@mcp.tool()
def memory_list(category: Optional[str] = None, limit: int = 20) -> str:
    """List memories (newest first)."""
    items = mem.get_all(category=category, limit=limit)
    if not items:
        return "No memories yet"
    lines = []
    for m in items:
        lines.append(f"[{m['id']}] [{m['category']}|{m['source']}] {m['content']}  ({m['created_at']})")
    return "\n".join(lines)


@mcp.tool()
def send_telegram(text: str, chat_id: str = "") -> str:
    """Send a Telegram message directly via Bot API. Millisecond delivery.
    Leave chat_id empty to use the default (TELEGRAM_CHAT_ID env var)."""
    import os
    import urllib.request
    import urllib.parse

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        return "❌ TELEGRAM_BOT_TOKEN not configured"
    target = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not target:
        return "❌ No chat_id specified and TELEGRAM_CHAT_ID not set"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": target, "text": text,
    }).encode()
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json as _j
            result = _j.loads(resp.read())
            if result.get("ok"):
                mem.bus_post("chat", "out", text)
                return "✅ Message sent to Telegram"
            return f"❌ Telegram API error: {result.get('description', 'unknown')}"
    except Exception as e:
        return f"❌ Send failed: {str(e)}"


@mcp.tool()
def send_wechat(text: str) -> str:
    """Send a WeChat message via iLink Bot. Requires the WeChat channel to be running
    and a valid context_token (the user must have sent a message recently)."""
    import json as _j
    import urllib.request

    # Read bot account info
    accounts_dir = Path.home() / ".wechat-claude" / "accounts"
    account_files = list(accounts_dir.glob("*.json")) if accounts_dir.exists() else []
    if not account_files:
        return "❌ No WeChat bot account found. Start the WeChat channel and scan QR first."

    with open(account_files[0]) as f:
        account = _j.load(f)
    base_url = account.get("baseUrl", "https://ilinkai.weixin.qq.com")
    bot_token = account.get("token", "")

    # Read context_token
    token_file = Path.home() / ".wechat-claude" / "context-tokens.json"
    if not token_file.exists():
        return "❌ No context_token. The user needs to send a WeChat message first."

    with open(token_file) as f:
        tokens = _j.load(f)

    if not tokens:
        return "❌ context_token is empty. The user needs to send a WeChat message first."

    # Use the first user's token
    user_id = list(tokens.keys())[0]
    context_token = tokens[user_id]["token"]

    # Build request
    import uuid
    import base64
    body = _j.dumps({
        "msg": {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": f"wechat-claude-{uuid.uuid4().hex[:8]}",
            "message_type": 2,
            "message_state": 2,
            "item_list": [{"type": 1, "text_item": {"text": text}}],
            "context_token": context_token,
        },
        "base_info": {"channel_version": "1.0.0"},
    }).encode()

    uin = base64.b64encode(uuid.uuid4().bytes).decode()
    url = f"{base_url}/ilink/bot/sendmessage"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("AuthorizationType", "ilink_bot_token")
    req.add_header("Authorization", f"Bearer {bot_token}")
    req.add_header("X-WECHAT-UIN", uin)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _j.loads(resp.read())
            err_code = result.get("errcode", result.get("err_code", 0))
            if err_code == 0:
                mem.bus_post("wechat", "out", text)
                return "✅ WeChat message sent"
            return f"❌ iLink API error: {_j.dumps(result, ensure_ascii=False)}"
    except Exception as e:
        return f"❌ Send failed: {str(e)}"


@mcp.tool()
def read_wechat(limit: int = 10) -> str:
    """Read recent WeChat inbox messages. Returns the last N messages received from the user.
    limit: number of messages to return, default 10, max 50."""
    import json as _j

    inbox_file = Path.home() / ".wechat-claude" / "inbox.json"
    if not inbox_file.exists():
        return "📭 Inbox empty (WeChat channel not running or no messages received yet)"

    try:
        with open(inbox_file) as f:
            inbox = _j.load(f)
    except Exception:
        return "❌ Failed to read inbox"

    if not inbox:
        return "📭 Inbox empty"

    limit = min(max(1, limit), 50)
    recent = inbox[-limit:]

    lines = []
    for msg in recent:
        ts = msg.get("ts", "?")[:19].replace("T", " ")
        text = msg.get("text", "")
        lines.append(f"[{ts}] {text}")

    return "\n".join(lines)


@mcp.tool()
def send_telegram_photo(file_path: str, caption: str = "", chat_id: str = "") -> str:
    """Send a local file/photo to Telegram. Supports images (jpg/png/gif/webp) and any file type.
    file_path: absolute path to local file. caption: optional description."""
    import os
    import uuid
    import urllib.request

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        return "❌ TELEGRAM_BOT_TOKEN not configured"
    target = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not target:
        return "❌ No chat_id specified"

    fp = Path(file_path)
    if not fp.exists():
        return f"❌ File not found: {file_path}"
    size_mb = fp.stat().st_size / (1024 * 1024)

    ext = fp.suffix.lower()
    is_photo = ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp')
    if is_photo and size_mb > 10:
        return f"❌ Photo too large ({size_mb:.1f}MB), Telegram limit is 10MB"
    if size_mb > 50:
        return f"❌ File too large ({size_mb:.1f}MB), Telegram limit is 50MB"

    method = "sendPhoto" if is_photo else "sendDocument"
    field_name = "photo" if is_photo else "document"
    url = f"https://api.telegram.org/bot{bot_token}/{method}"

    boundary = uuid.uuid4().hex
    file_data = fp.read_bytes()
    parts = []
    for k, v in [("chat_id", target), ("caption", caption), ("parse_mode", "Markdown")]:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}".encode())
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field_name}\"; filename=\"{fp.name}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n".encode() + file_data
    )
    body = b"\r\n".join(parts) + f"\r\n--{boundary}--\r\n".encode()

    try:
        req = urllib.request.Request(url, data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            import json as _j
            result = _j.loads(resp.read())
            if result.get("ok"):
                return f"✅ File sent to Telegram: {fp.name}"
            return f"❌ Telegram API error: {result.get('description', 'unknown')}"
    except Exception as e:
        return f"❌ Send failed: {str(e)}"


@mcp.tool()
def system_status() -> str:
    """Check system health: CPU, memory, disk, and service status."""
    try:
        import psutil
    except ImportError:
        return "❌ psutil not installed. Run: pip install psutil"

    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    lines = [
        "💻 System Resources",
        f"  CPU: {cpu}% | RAM: {ram.used / (1024**3):.1f}/{ram.total / (1024**3):.1f} GB ({ram.percent}%) | "
        f"Disk: {disk.used / (1024**3):.0f}/{disk.total / (1024**3):.0f} GB ({disk.percent}%)",
        "", "🔧 Services",
    ]

    services = {
        "Memory HTTP (port 8000)": {"port": 8000},
        "Cloudflare Tunnel": {"grep": "cloudflared tunnel"},
        "Telegram Channel": {"grep": "channels plugin:telegram"},
        "WeChat Channel": {"grep": "dangerously-load-development-channels"},
        "Dashboard (port 3000)": {"port": 3000},
    }
    procs_cmdline = []
    try:
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmd = " ".join(p.info.get('cmdline') or [])
                if cmd:
                    procs_cmdline.append(cmd)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

    listening_ports = set()
    try:
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN':
                listening_ports.add(conn.laddr.port)
    except (psutil.AccessDenied, OSError):
        pass

    for name, check in services.items():
        running = False
        if "port" in check:
            running = check["port"] in listening_ports
        if "grep" in check:
            running = any(check["grep"] in cmd for cmd in procs_cmdline)
        lines.append(f"  {'✅' if running else '⛔'} {name}")

    pid_file = Path(__file__).parent / ".pid-heartbeat"
    hb_running = False
    if pid_file.exists():
        try:
            hb_running = psutil.pid_exists(int(pid_file.read_text().strip()))
        except Exception:
            pass
    lines.append(f"  {'✅' if hb_running else '⛔'} Heartbeat Agent")
    return "\n".join(lines)


@mcp.tool()
def read_webpage(url: str, max_length: int = 5000) -> str:
    """Fetch a webpage and extract text content. Good for reading articles, docs, etc.
    max_length: max characters to return."""
    import urllib.request
    import html.parser
    import re

    if not url.startswith(("http://", "https://")):
        return "❌ Only http/https URLs supported"

    class TextExtractor(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.texts, self.skip_tags = [], {'script', 'style', 'nav', 'footer', 'header', 'noscript'}
            self.skip_depth, self.title, self.in_title = 0, "", False
        def handle_starttag(self, tag, attrs):
            if tag in self.skip_tags: self.skip_depth += 1
            if tag == 'title': self.in_title = True
        def handle_endtag(self, tag):
            if tag in self.skip_tags and self.skip_depth > 0: self.skip_depth -= 1
            if tag == 'title': self.in_title = False
        def handle_data(self, data):
            if self.in_title: self.title = data.strip()
            elif self.skip_depth == 0 and data.strip(): self.texts.append(data.strip())

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "text" not in ct and "html" not in ct and "json" not in ct:
                return f"❌ Non-text content: {ct}"
            raw = resp.read(1024 * 1024)
            charset = "utf-8"
            if "charset=" in ct:
                charset = ct.split("charset=")[-1].split(";")[0].strip()
            body = raw.decode(charset, errors="replace")
        if "json" in ct:
            return body[:max_length]
        parser = TextExtractor()
        parser.feed(body)
        text = re.sub(r'\n{3,}', '\n\n', "\n".join(parser.texts))
        result = f"📄 {parser.title or '(untitled)'}\n\n{text}"
        return result[:max_length] + ("\n\n... (truncated)" if len(result) > max_length else "")
    except Exception as e:
        return f"❌ Fetch failed: {str(e)}"


@mcp.tool()
def spotify_control(action: str, value: str = "") -> str:
    """Control Spotify playback (macOS only).
    action: play/pause/toggle/next/prev/status/volume_up/volume_down/set_volume/play_track
    value: volume (0-100) for set_volume, Spotify URI for play_track."""
    import subprocess

    scripts = {
        "play": 'tell application "Spotify" to play',
        "pause": 'tell application "Spotify" to pause',
        "toggle": 'tell application "Spotify" to playpause',
        "next": 'tell application "Spotify" to next track',
        "prev": 'tell application "Spotify" to previous track',
        "status": '''tell application "Spotify"
            set t to name of current track
            set a to artist of current track
            set al to album of current track
            set pos to player position
            set dur to duration of current track
            set vol to sound volume
            set st to player state as string
            return t & "|" & a & "|" & al & "|" & (pos as integer) & "|" & ((dur / 1000) as integer) & "|" & vol & "|" & st
        end tell''',
        "volume_up": 'tell application "Spotify"\nset v to sound volume\nset sound volume to (v + 10)\nif sound volume > 100 then set sound volume to 100\nreturn "Volume: " & sound volume & "%"\nend tell',
        "volume_down": 'tell application "Spotify"\nset v to sound volume\nset sound volume to (v - 10)\nif sound volume < 0 then set sound volume to 0\nreturn "Volume: " & sound volume & "%"\nend tell',
    }

    if action == "set_volume":
        try:
            vol = max(0, min(100, int(value)))
        except ValueError:
            return "❌ Provide a number 0-100"
        script = f'tell application "Spotify" to set sound volume to {vol}\nreturn "Volume: {vol}%"'
    elif action == "play_track":
        if not value:
            return "❌ Provide a Spotify URI (e.g. spotify:track:xxx)"
        safe_uri = value.replace('"', '').replace('\\', '')
        script = f'tell application "Spotify" to play track "{safe_uri}"'
    elif action in scripts:
        script = scripts[action]
    else:
        return f"❌ Unknown action: {action}\nAvailable: play, pause, toggle, next, prev, status, volume_up, volume_down, set_volume, play_track"

    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            err = result.stderr.strip()
            if "is not running" in err:
                return "❌ Spotify is not running"
            return f"❌ {err}"
        output = result.stdout.strip()
        if action == "status" and "|" in output:
            parts = output.split("|")
            if len(parts) >= 7:
                name, artist, album, pos, dur, vol, state = parts[:7]
                pm, ps = divmod(int(pos), 60)
                dm, ds = divmod(int(dur), 60)
                return f"🎵 {name} — {artist}\n💿 {album}\n⏱ {pm}:{ps:02d} / {dm}:{ds:02d}\n🔊 {vol}%  |  {state}"
        return f"✅ {output or action + ' done'}"
    except subprocess.TimeoutExpired:
        return "❌ Timeout"
    except FileNotFoundError:
        return "❌ osascript not available (macOS only)"


@mcp.tool()
def morning_briefing(latitude: float = 0, longitude: float = 0,
                     timezone_name: str = "UTC", chat_id: str = "",
                     calendar_summary: str = "") -> str:
    """Generate and send a morning briefing to Telegram: weather + calendar + pending tasks.
    Set latitude/longitude for weather (e.g. 40.71, -74.01 for NYC).
    calendar_summary: optional pre-formatted calendar info."""
    import os
    import urllib.request
    import json as _json

    lat = latitude or float(os.environ.get("WEATHER_LAT", "0"))
    lon = longitude or float(os.environ.get("WEATHER_LON", "0"))
    tz = timezone_name if timezone_name != "UTC" else os.environ.get("WEATHER_TZ", "UTC")

    sections = ["*☀️ Morning Briefing*\n"]

    # Weather (Open-Meteo, free, no API key)
    if lat != 0 and lon != 0:
        try:
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
                f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                f"&timezone={tz.replace('/', '%2F')}&forecast_days=1"
            )
            with urllib.request.urlopen(urllib.request.Request(weather_url), timeout=10) as resp:
                w = _json.loads(resp.read())
            codes = {0:"☀️ Clear",1:"🌤 Mostly clear",2:"⛅ Cloudy",3:"☁️ Overcast",
                     45:"🌫 Fog",51:"🌦 Drizzle",61:"🌧 Rain",71:"🌨 Snow",
                     80:"🌧 Showers",95:"⛈ Thunderstorm"}
            desc = codes.get(w["current"]["weather_code"], f"Code {w['current']['weather_code']}")
            sections.append(
                f"*🌤 Weather*\n"
                f"  {desc} {w['current']['temperature_2m']}°C\n"
                f"  High {w['daily']['temperature_2m_max'][0]}° / Low {w['daily']['temperature_2m_min'][0]}° | "
                f"Rain {w['daily']['precipitation_probability_max'][0]}%"
            )
        except Exception as e:
            sections.append(f"*🌤 Weather*\n  Failed to fetch: {str(e)[:50]}")
    else:
        sections.append("*🌤 Weather*\n  Set WEATHER_LAT/WEATHER_LON env vars to enable")

    # Calendar
    if calendar_summary:
        sections.append(f"*📅 Today's Schedule*\n{calendar_summary}")

    # Pending CC tasks
    try:
        tasks = mem.list_tasks(limit=10)
        pending = [t for t in tasks if t["status"] in ("pending", "running")]
        if pending:
            task_lines = "\n".join(f"  {'🔄' if t['status']=='running' else '⏳'} {t['prompt']}" for t in pending)
            sections.append(f"*📋 Pending Tasks*\n{task_lines}")
    except Exception:
        pass

    return send_telegram(text="\n\n".join(sections), chat_id=chat_id)


@mcp.tool()
def message_bus_read(limit: int = 20) -> str:
    """Read recent cross-channel messages. Every channel (Telegram/WeChat/Chat/CC) logs sent
    and received messages here. Use this to understand what happened in other channels."""
    return mem.bus_format(limit)


@mcp.tool()
def message_bus_post(source: str, direction: str, content: str) -> str:
    """Write a message to the cross-channel message bus.
    source: telegram/wechat/chat/cc_task/scheduled
    direction: in (user sent) / out (Claude sent)"""
    mem.bus_post(source, direction, content)
    return "✅ Written to message bus"


@mcp.tool()
def cc_execute(prompt: str) -> str:
    """Submit a task for local Claude Code to execute. For: writing code, running scripts, git ops, etc.
    Returns a task_id. Use cc_check(task_id) to check results later."""
    result = mem.submit_task(prompt=prompt, source="chat")
    mem.bus_post("cc_task", "out", f"[Task submitted] {prompt[:150]}")
    return f"✅ {result['message']}\nUse cc_check(task_id={result['task_id']}) to check results"


@mcp.tool()
def cc_check(task_id: int) -> str:
    """Check CC task status and results."""
    result = mem.check_task(task_id)
    if "error" in result:
        return f"❌ {result['error']}"
    lines = [f"Task #{result['task_id']}", f"Status: {result['status']}", f"Created: {result['created_at']}"]
    if result['started_at']: lines.append(f"Started: {result['started_at']}")
    if result['completed_at']: lines.append(f"Completed: {result['completed_at']}")
    if result['result']: lines.append(f"\n--- Result ---\n{result['result']}")
    else: lines.append("\n⏳ Still running...")
    return "\n".join(lines)


@mcp.tool()
def cc_tasks(limit: int = 5) -> str:
    """List recent CC tasks."""
    tasks = mem.list_tasks(limit=limit)
    if not tasks:
        return "No tasks"
    lines = []
    for t in tasks:
        icon = {"pending":"⏳","running":"🔄","completed":"✅","error":"❌","timeout":"⏰"}.get(t["status"],"❓")
        lines.append(f"{icon} #{t['task_id']} [{t['status']}] {t['prompt']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if is_http:
        import uvicorn
        import anyio
        import json as _json
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        # OAuth 2.0 credentials (stored in file, not hardcoded)
        CRED_FILE = Path.home() / ".imprint-oauth.json"
        if CRED_FILE.exists():
            _creds = _json.loads(CRED_FILE.read_text())
            CLIENT_ID = _creds["client_id"]
            CLIENT_SECRET = _creds["client_secret"]
            ACCESS_TOKEN = _creds["access_token"]
        else:
            import os as _os
            CLIENT_ID = _os.environ.get("OAUTH_CLIENT_ID", "")
            CLIENT_SECRET = _os.environ.get("OAUTH_CLIENT_SECRET", "")
            ACCESS_TOKEN = _os.environ.get("OAUTH_ACCESS_TOKEN", "")

        # Pending authorization codes: {code: {redirect_uri, expires_at}}
        import secrets as _secrets
        import time as _time
        _pending_auth_codes: dict = {}

        class OAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if request.url.path in ("/oauth/token", "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource", "/oauth/authorize"):
                    return await call_next(request)
                if not ACCESS_TOKEN:
                    return await call_next(request)
                # Localhost requests bypass auth (internal service calls)
                client = request.client
                if client and client.host in ("127.0.0.1", "::1", "localhost"):
                    return await call_next(request)
                auth = request.headers.get("authorization", "")
                if auth == f"Bearer {ACCESS_TOKEN}":
                    return await call_next(request)
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        app = mcp.streamable_http_app()
        from starlette.routing import Route as _Route
        mcp_route = app.routes[0]
        app.routes.append(_Route("/", mcp_route.endpoint, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]))

        from starlette.routing import Route
        from starlette.requests import Request

        async def oauth_protected_resource(request: Request):
            """OAuth 2.0 Protected Resource Metadata (RFC 9728)"""
            base = str(request.base_url).rstrip("/")
            return JSONResponse({
                "resource": base,
                "authorization_servers": [base],
            })

        async def oauth_metadata(request: Request):
            """OAuth 2.0 Authorization Server Metadata (RFC 8414)"""
            base = str(request.base_url).rstrip("/")
            return JSONResponse({
                "issuer": base,
                "authorization_endpoint": f"{base}/oauth/authorize",
                "token_endpoint": f"{base}/oauth/token",
                "grant_types_supported": ["authorization_code", "client_credentials"],
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["client_secret_post"],
            })

        async def oauth_authorize(request: Request):
            """Auto-approve and redirect back with a one-time authorization code"""
            from urllib.parse import urlencode
            redirect_uri = request.query_params.get("redirect_uri", "")
            state = request.query_params.get("state", "")
            if not redirect_uri:
                return JSONResponse({"error": "missing redirect_uri"}, status_code=400)
            # Generate a random one-time auth code (not the access token)
            code = _secrets.token_urlsafe(32)
            _pending_auth_codes[code] = {
                "redirect_uri": redirect_uri,
                "expires_at": _time.time() + 300,  # 5 minutes
            }
            params = {"code": code, "state": state}
            from starlette.responses import RedirectResponse
            return RedirectResponse(f"{redirect_uri}?{urlencode(params)}")

        async def oauth_token(request: Request):
            """OAuth 2.0 token endpoint"""
            from urllib.parse import unquote_plus
            body = await request.body()
            try:
                params = {
                    k: unquote_plus(v)
                    for k, v in (x.split("=", 1) for x in body.decode().split("&") if "=" in x)
                }
            except Exception:
                try:
                    params = _json.loads(body)
                except Exception:
                    return JSONResponse({"error": "invalid_request"}, status_code=400)

            grant_type = params.get("grant_type", "")

            # Client credentials grant — requires valid client_id + secret
            if grant_type == "client_credentials":
                if (CLIENT_ID and CLIENT_SECRET
                        and params.get("client_id") == CLIENT_ID
                        and params.get("client_secret") == CLIENT_SECRET):
                    return JSONResponse({
                        "access_token": ACCESS_TOKEN,
                        "token_type": "bearer",
                        "expires_in": 86400,
                    })
                return JSONResponse({"error": "invalid_client"}, status_code=401)

            # Authorization code grant — validate code, redirect_uri, and credentials
            if grant_type == "authorization_code":
                code = params.get("code", "")
                # Expire stale codes
                now = _time.time()
                expired = [k for k, v in _pending_auth_codes.items() if v["expires_at"] < now]
                for k in expired:
                    del _pending_auth_codes[k]

                pending = _pending_auth_codes.pop(code, None)  # one-time use
                if not pending:
                    return JSONResponse({"error": "invalid_grant", "error_description": "unknown or expired code"}, status_code=400)
                if params.get("redirect_uri", "") != pending["redirect_uri"]:
                    return JSONResponse({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, status_code=400)
                # Validate client credentials when configured
                if CLIENT_ID and CLIENT_SECRET:
                    if (params.get("client_id") != CLIENT_ID
                            or params.get("client_secret") != CLIENT_SECRET):
                        return JSONResponse({"error": "invalid_client"}, status_code=401)
                return JSONResponse({
                    "access_token": ACCESS_TOKEN,
                    "token_type": "bearer",
                    "expires_in": 86400,
                })

            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        app.routes.insert(0, Route("/.well-known/oauth-protected-resource", oauth_protected_resource, methods=["GET"]))
        app.routes.insert(1, Route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET"]))
        app.routes.insert(2, Route("/oauth/authorize", oauth_authorize, methods=["GET"]))
        app.routes.insert(3, Route("/oauth/token", oauth_token, methods=["POST"]))
        app.add_middleware(OAuthMiddleware)

        print(f"Memory HTTP mode (OAuth): http://0.0.0.0:8000/mcp", flush=True)
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        anyio.run(server.serve)
    else:
        mcp.run(transport="stdio")
