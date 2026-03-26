#!/usr/bin/env python3
"""
Claude Imprint — Dashboard
localhost:3000 — manage all components: start/stop/status
"""

import os
import subprocess
import signal
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import psutil
import uvicorn

app = FastAPI(title="Claude Imprint")
BASE = Path(__file__).parent
LOGS = BASE / "logs"
LOGS.mkdir(exist_ok=True)

# ─── Components ──────────────────────────────────────────

COMPONENTS = {
    "memory_http": {
        "name": "🧠 Memory HTTP",
        "pid_file": ".pid-http",
        "start_cmd": ["python3", str(BASE / "memory_mcp.py"), "--http"],
        "log_file": "logs/http.log",
        "type": "background",
        "check_port": 8000,
    },
    "tunnel": {
        "name": "🌐 Cloudflare Tunnel",
        "pid_file": ".pid-tunnel",
        "start_cmd": ["cloudflared", "tunnel", "run", "my-tunnel"],
        "log_file": "logs/tunnel.log",
        "type": "background",
        "grep_pattern": "cloudflared tunnel",
    },
    "telegram": {
        "name": "📨 Telegram",
        "grep_pattern": "channels plugin:telegram",
        "terminal_cmd": "claude --permission-mode auto --channels plugin:telegram@claude-plugins-official",
        "type": "terminal",
    },
    "wechat": {
        "name": "📱 WeChat",
        "grep_pattern": "dangerously-load-development-channels server:wechat",
        "terminal_cmd": "claude --permission-mode auto --dangerously-load-development-channels server:wechat",
        "type": "terminal",
    },
}


# ─── Status Detection ────────────────────────────────────

def get_pid_status(comp):
    """Check background process status: port → grep → PID file"""
    # Method 1: port detection (lsof, no root needed)
    if "check_port" in comp:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{comp['check_port']}"],
                capture_output=True, text=True, timeout=3
            )
            pids = [p for p in result.stdout.strip().split("\n") if p]
            if pids:
                return {"running": True, "pid": int(pids[0])}
        except Exception:
            pass
    # Method 2: process name grep
    if "grep_pattern" in comp:
        try:
            result = subprocess.run(
                ["pgrep", "-f", comp["grep_pattern"]],
                capture_output=True, text=True, timeout=3
            )
            pids = [p for p in result.stdout.strip().split("\n") if p]
            if pids:
                return {"running": True, "pid": int(pids[0])}
        except Exception:
            pass
    # Method 3: PID file fallback
    pid_path = BASE / comp.get("pid_file", "")
    if pid_path and pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            if psutil.pid_exists(pid):
                p = psutil.Process(pid)
                if p.status() != psutil.STATUS_ZOMBIE:
                    return {"running": True, "pid": pid}
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        pid_path.unlink(missing_ok=True)
    return {"running": False, "pid": None}


def get_terminal_status(comp):
    """Check terminal window process status"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", comp["grep_pattern"]],
            capture_output=True, text=True, timeout=3
        )
        pids = result.stdout.strip().split("\n")
        pids = [p for p in pids if p]
        return {"running": len(pids) > 0, "pid": int(pids[0]) if pids else None}
    except Exception:
        return {"running": False, "pid": None}


def get_tunnel_url():
    """Return tunnel URL if running"""
    status = get_pid_status(COMPONENTS["tunnel"])
    if status["running"]:
        return "https://your-domain.example.com"
    return None


def get_claude_auth():
    """Check Claude Code auth status"""
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout + result.stderr
        if "expired" in output.lower():
            return "expired"
        if "authenticated" in output.lower() or "logged in" in output.lower():
            return "ok"
        return "unknown"
    except Exception:
        return "unknown"


def get_memory_stats():
    """Get memory stats"""
    db_path = BASE / "memory.db"
    if not db_path.exists():
        return {"count": 0, "today_logs": 0}
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        conn.close()

        from datetime import datetime, timezone, timedelta
        tz = timezone(timedelta(hours=int(os.environ.get("TZ_OFFSET", 0))))
        today = datetime.now(tz).strftime("%Y-%m-%d")
        log_file = BASE / "memory" / f"{today}.md"
        today_logs = 0
        if log_file.exists():
            today_logs = len([l for l in log_file.read_text().splitlines() if l.strip()])
        return {"count": count, "today_logs": today_logs}
    except Exception:
        return {"count": 0, "today_logs": 0}


def get_scheduled_tasks():
    """Read scheduled tasks directory"""
    tasks_dir = Path.home() / ".claude" / "scheduled-tasks"
    if not tasks_dir.exists():
        return []
    tasks = []
    import yaml
    for d in sorted(tasks_dir.iterdir()):
        skill = d / "SKILL.md"
        if not skill.exists():
            continue
        text = skill.read_text()
        # parse frontmatter
        meta = {"id": d.name, "name": d.name, "description": ""}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1])
                    if fm:
                        meta["name"] = fm.get("name", d.name)
                        meta["description"] = fm.get("description", "")
                except Exception:
                    pass
        tasks.append(meta)
    return tasks


def get_heatmap_data():
    """Get interaction data for the past 365 days"""
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=int(os.environ.get("TZ_OFFSET", 0))))
    today = datetime.now(tz).date()
    data = {}

    # Count memories per day from memory.db
    db_path = BASE / "memory.db"
    if db_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT DATE(created_at) as d, COUNT(*) as c FROM memories GROUP BY DATE(created_at)"
        ).fetchall()
        conn.close()
        for d, c in rows:
            if d:
                data[d] = data.get(d, 0) + c

    # Also count daily log lines
    mem_dir = BASE / "memory"
    if mem_dir.exists():
        for f in mem_dir.glob("????-??-??.md"):
            d = f.stem
            lines = len([l for l in f.read_text().splitlines() if l.strip() and not l.startswith("#")])
            if lines > 0:
                data[d] = data.get(d, 0) + lines

    # Assemble last 365 days
    result = []
    for i in range(364, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        result.append({"date": d, "count": data.get(d, 0)})
    return result


# ─── API ────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    statuses = {}
    for key, comp in COMPONENTS.items():
        if comp["type"] == "background":
            status = get_pid_status(comp)
        else:
            status = get_terminal_status(comp)
        status["name"] = comp["name"]
        status["type"] = comp["type"]
        statuses[key] = status

    tunnel_url = get_tunnel_url()
    memory = get_memory_stats()
    tasks = get_scheduled_tasks()

    return {
        "components": statuses,
        "tunnel_url": tunnel_url,
        "memory": memory,
        "tasks": tasks,
    }


@app.post("/api/{component}/start")
async def api_start(component: str):
    if component not in COMPONENTS:
        return JSONResponse({"error": "unknown component"}, 404)

    comp = COMPONENTS[component]

    if comp["type"] == "background":
        log_path = BASE / comp["log_file"]
        with open(log_path, "a") as log:
            proc = subprocess.Popen(
                comp["start_cmd"],
                stdout=log, stderr=log,
                cwd=str(BASE),
                start_new_session=True,
            )
        pid_path = BASE / comp["pid_file"]
        pid_path.write_text(str(proc.pid))
        return {"ok": True, "pid": proc.pid}
    else:
        # Terminal window
        cmd = comp["terminal_cmd"]
        subprocess.run([
            "osascript", "-e",
            f'tell application "Terminal" to do script "{cmd}"'
        ], capture_output=True)
        return {"ok": True}


@app.post("/api/{component}/stop")
async def api_stop(component: str):
    if component not in COMPONENTS:
        return JSONResponse({"error": "unknown component"}, 404)

    comp = COMPONENTS[component]

    if comp["type"] == "background":
        # Get actual PID via status detection
        status = get_pid_status(comp)
        if status["running"] and status["pid"]:
            try:
                os.kill(status["pid"], signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        # Clean up PID file
        pid_file = comp.get("pid_file", "")
        if pid_file:
            pid_path = BASE / pid_file
            pid_path.unlink(missing_ok=True)
        return {"ok": True}
    else:
        # Can't force-kill terminal sessions
        return {"ok": True, "message": "Please close the terminal window manually (Ctrl+C)"}


@app.get("/api/heatmap")
async def api_heatmap():
    """Return heatmap data"""
    return {"days": get_heatmap_data()}


@app.get("/api/memories")
async def api_memories(q: str = "", limit: int = 20):
    """Search or list memories"""
    db_path = BASE / "memory.db"
    if not db_path.exists():
        return {"memories": []}
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    if q:
        rows = conn.execute(
            "SELECT id, content, category, source, importance, created_at FROM memories WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{q}%", limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, content, category, source, importance, created_at FROM memories ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return {"memories": [dict(r) for r in rows]}


@app.delete("/api/memories/{memory_id}")
async def api_delete_memory(memory_id: int):
    """Delete a memory"""
    db_path = BASE / "memory.db"
    if not db_path.exists():
        return {"ok": False, "error": "Database not found"}
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM memory_vectors WHERE memory_id = ?", (memory_id,))
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.put("/api/memories/{memory_id}")
async def api_update_memory(memory_id: int, request: Request):
    """Update a memory"""
    db_path = BASE / "memory.db"
    if not db_path.exists():
        return {"ok": False, "error": "Database not found"}
    import sqlite3
    body = await request.json()
    content = body.get("content", "")
    category = body.get("category", "")
    importance = body.get("importance", 5)
    if not content:
        return {"ok": False, "error": "Content cannot be empty"}
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE memories SET content = ?, category = ?, importance = ? WHERE id = ?",
        (content, category, importance, memory_id),
    )
    # Delete old vector embedding (content changed, old embedding is stale)
    conn.execute("DELETE FROM memory_vectors WHERE memory_id = ?", (memory_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/remote-tools")
async def api_remote_tools():
    """Get remote tool call log (cc_tasks etc.)"""
    db_path = BASE / "memory.db"
    if not db_path.exists():
        return {"tasks": []}
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, prompt, status, result, source, created_at, completed_at FROM cc_tasks ORDER BY id DESC LIMIT 20"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []  # table doesn't exist yet
    conn.close()
    return {"tasks": [dict(r) for r in rows]}


@app.get("/api/logs/{component}")
async def api_logs(component: str, lines: int = 30):
    """Get recent logs"""
    comp = COMPONENTS.get(component)
    if not comp or "log_file" not in comp:
        return {"logs": "No logs"}
    log_path = BASE / comp["log_file"]
    if not log_path.exists():
        return {"logs": "Log file not found"}
    try:
        all_lines = log_path.read_text().splitlines()
        return {"logs": "\n".join(all_lines[-lines:])}
    except Exception as e:
        return {"logs": f"Read error: {e}"}


# ─── Frontend ────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Imprint</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #FAF9F5;
    color: #3D3D3A;
    min-height: 100vh;
    padding: 20px;
  }
  .header {
    text-align: center;
    padding: 30px 0 20px;
  }
  .header h1 {
    font-size: 28px;
    color: #B96748;
    margin-bottom: 8px;
  }
  .header .subtitle {
    color: #B0AEA5;
    font-size: 14px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
    max-width: 900px;
    margin: 20px auto;
  }
  .card {
    background: #FFFFFF;
    border: 1px solid #E8E6DC;
    border-radius: 12px;
    padding: 20px;
    transition: border-color 0.3s, box-shadow 0.3s;
  }
  .card:hover { border-color: #B96748; box-shadow: 0 2px 12px rgba(185,103,72,0.08); }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
  }
  .card-name { font-size: 16px; font-weight: 600; color: #3D3D3A; }
  .status-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 8px;
  }
  .status-dot.on { background: #B96748; box-shadow: 0 0 8px rgba(185,103,72,0.4); }
  .status-dot.off { background: #B0AEA5; }
  .status-dot.warn { background: #F59E0B; box-shadow: 0 0 8px rgba(245,158,11,0.4); }
  .toggle {
    position: relative;
    width: 44px; height: 24px;
    cursor: pointer;
  }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .toggle .slider {
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: #D5D3C9;
    border-radius: 12px;
    transition: 0.3s;
  }
  .toggle .slider:before {
    content: "";
    position: absolute;
    height: 18px; width: 18px;
    left: 3px; bottom: 3px;
    background: #fff;
    border-radius: 50%;
    transition: 0.3s;
  }
  .toggle input:checked + .slider { background: #B96748; }
  .toggle input:checked + .slider:before { transform: translateX(20px); }
  .card-info {
    font-size: 12px;
    color: #B0AEA5;
    margin-top: 8px;
  }
  .info-bar {
    max-width: 900px;
    margin: 20px auto;
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
  }
  .info-chip {
    background: #FFFFFF;
    border: 1px solid #E8E6DC;
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 13px;
    flex: 1;
    min-width: 200px;
  }
  .info-chip .label { color: #B0AEA5; margin-bottom: 4px; }
  .info-chip .value { color: #B96748; font-family: monospace; word-break: break-all; }
  .memory-section {
    max-width: 900px;
    margin: 20px auto;
    background: #FFFFFF;
    border: 1px solid #E8E6DC;
    border-radius: 12px;
    padding: 20px;
  }
  .memory-section h2 {
    font-size: 18px;
    margin-bottom: 12px;
    color: #B96748;
  }
  .search-box {
    width: 100%;
    padding: 8px 12px;
    background: #FFFFFF;
    border: 1px solid #E8E6DC;
    border-radius: 8px;
    color: #3D3D3A;
    font-size: 14px;
    margin-bottom: 12px;
  }
  .search-box:focus { outline: none; border-color: #B96748; }
  .memory-item {
    padding: 10px 0;
    border-bottom: 1px solid #E8E6DC;
    font-size: 13px;
    color: #3D3D3A;
    position: relative;
  }
  .memory-item:last-child { border-bottom: none; }
  .memory-item:hover .memory-actions { opacity: 1; }
  .memory-meta { color: #B0AEA5; font-size: 11px; margin-top: 2px; }
  .memory-actions {
    opacity: 0;
    transition: opacity 0.15s;
    position: absolute;
    right: 0;
    top: 8px;
    display: flex;
    gap: 4px;
  }
  .memory-actions button {
    background: none;
    border: 1px solid #E8E6DC;
    color: #B0AEA5;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
  }
  .memory-actions button:hover { border-color: #B96748; color: #B96748; }
  .memory-actions button.del:hover { border-color: #c0392b; color: #c0392b; }
  .modal-overlay {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.4);
    z-index: 100;
    justify-content: center;
    align-items: center;
  }
  .modal-overlay.active { display: flex; }
  .modal {
    background: #FFFFFF;
    border-radius: 12px;
    padding: 24px;
    width: 500px;
    max-width: 90vw;
    box-shadow: 0 8px 32px rgba(0,0,0,0.15);
  }
  .modal h3 { color: #B96748; margin-bottom: 16px; font-size: 16px; }
  .modal textarea {
    width: 100%;
    min-height: 100px;
    padding: 8px 12px;
    border: 1px solid #E8E6DC;
    border-radius: 8px;
    font-size: 13px;
    color: #3D3D3A;
    resize: vertical;
    font-family: inherit;
  }
  .modal textarea:focus { outline: none; border-color: #B96748; }
  .modal-row { display: flex; gap: 12px; margin-top: 12px; }
  .modal-row select, .modal-row input {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid #E8E6DC;
    border-radius: 6px;
    font-size: 13px;
    color: #3D3D3A;
  }
  .modal-buttons { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
  .modal-buttons button {
    padding: 6px 16px;
    border-radius: 6px;
    font-size: 13px;
    cursor: pointer;
    border: 1px solid #E8E6DC;
    background: #FFFFFF;
    color: #3D3D3A;
  }
  .modal-buttons button.save { background: #B96748; color: #FFFFFF; border-color: #B96748; }
  .modal-buttons button.save:hover { background: #a05538; }
  .log-btn {
    background: none;
    border: 1px solid #E8E6DC;
    color: #B0AEA5;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    cursor: pointer;
    margin-top: 4px;
  }
  .log-btn:hover { border-color: #B96748; color: #B96748; }
  .lang-btn {
    position: absolute;
    right: 20px;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.3);
    color: #FFFFFF;
    padding: 4px 12px;
    border-radius: 6px;
    font-size: 12px;
    cursor: pointer;
    transition: background 0.2s;
  }
  .lang-btn:hover { background: rgba(255,255,255,0.25); }
  .header { position: relative; }
  .tasks-section {
    max-width: 900px;
    margin: 20px auto;
    background: #FFFFFF;
    border: 1px solid #E8E6DC;
    border-radius: 12px;
    padding: 20px;
  }
  .tasks-section h2 {
    font-size: 18px;
    margin-bottom: 12px;
    color: #B96748;
  }
  .task-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid #E8E6DC;
    font-size: 13px;
  }
  .task-item:last-child { border-bottom: none; }
  .task-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #B96748;
    box-shadow: 0 0 6px rgba(185,103,72,0.3);
    flex-shrink: 0;
  }
  .heatmap-section {
    max-width: 900px;
    margin: 20px auto;
    background: #FFFFFF;
    border: 1px solid #E8E6DC;
    border-radius: 12px;
    padding: 20px;
  }
  .heatmap-section h2 {
    font-size: 18px;
    margin-bottom: 4px;
    color: #B96748;
  }
  .heatmap-subtitle {
    font-size: 12px;
    color: #B0AEA5;
    margin-bottom: 14px;
  }
  .heatmap-wrap {
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  .heatmap-months {
    display: flex;
    font-size: 10px;
    color: #B0AEA5;
    margin-bottom: 4px;
    margin-left: 32px;
  }
  .heatmap-months span {
    flex: 1;
    min-width: 0;
  }
  .heatmap-days {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 10px;
    color: #B0AEA5;
    padding-top: 1px;
  }
  .heatmap-days span {
    height: 12px;
    line-height: 12px;
    width: 24px;
    text-align: right;
    padding-right: 4px;
  }
  .heatmap-grid {
    display: flex;
    gap: 3px;
    overflow-x: auto;
  }
  .heatmap-col {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .heatmap-cell {
    width: 12px; height: 12px;
    border-radius: 2px;
    background: #EBEAE2;
    position: relative;
    cursor: default;
  }
  .heatmap-cell[data-level="1"] { background: #F0D1C2; }
  .heatmap-cell[data-level="2"] { background: #DDA58A; }
  .heatmap-cell[data-level="3"] { background: #C97B5A; }
  .heatmap-cell[data-level="4"] { background: #B96748; }
  .heatmap-cell .tooltip {
    display: none;
    position: absolute;
    bottom: 18px; left: 50%;
    transform: translateX(-50%);
    background: #3D3D3A;
    color: #fff;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
    white-space: nowrap;
    z-index: 10;
  }
  .heatmap-cell:hover .tooltip { display: block; }
  .heatmap-legend {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 10px;
    font-size: 11px;
    color: #B0AEA5;
    justify-content: flex-end;
  }
  .heatmap-legend .heatmap-cell { cursor: default; width: 10px; height: 10px; }
  .task-name { font-weight: 600; color: #3D3D3A; }
  .task-desc { color: #B0AEA5; font-size: 12px; }
  .log-box {
    background: #FFFFFF;
    border-radius: 6px;
    padding: 8px;
    font-family: monospace;
    font-size: 11px;
    color: #B0AEA5;
    max-height: 150px;
    overflow-y: auto;
    margin-top: 8px;
    white-space: pre-wrap;
    display: none;
  }
</style>
</head>
<body>

<div class="header">
  <h1>✨ Claude Imprint</h1>
  <div class="subtitle" id="auth-status">Loading...</div>
  <button class="lang-btn" onclick="toggleLang()" title="Switch language">🌐 <span id="lang-label">中文</span></button>
</div>

<div class="grid" id="components"></div>

<div class="info-bar">
  <div class="info-chip">
    <div class="label">Tunnel URL</div>
    <div class="value" id="tunnel-url">-</div>
  </div>
  <div class="info-chip">
    <div class="label">Memories</div>
    <div class="value" id="memory-count">-</div>
  </div>
  <div class="info-chip">
    <div class="label">Today's Logs</div>
    <div class="value" id="today-logs">-</div>
  </div>
</div>

<div class="heatmap-section">
  <h2>📊 Interaction Heatmap</h2>
  <div class="heatmap-subtitle">Darker = more activity that day</div>
  <div id="heatmap">Loading...</div>
  <div class="heatmap-legend">
    <span>Less</span>
    <div class="heatmap-cell"></div>
    <div class="heatmap-cell" data-level="1"></div>
    <div class="heatmap-cell" data-level="2"></div>
    <div class="heatmap-cell" data-level="3"></div>
    <div class="heatmap-cell" data-level="4"></div>
    <span>More</span>
  </div>
</div>

<div class="tasks-section">
  <h2>⏰ Scheduled Tasks</h2>
  <div id="tasks-list">Loading...</div>
</div>

<div class="tasks-section">
  <h2>🔧 Remote Tool Log</h2>
  <div class="heatmap-subtitle">Tool calls from Claude.ai chat</div>
  <div id="remote-tools" style="margin-top:12px;max-height:400px;overflow-y:scroll;">Loading...</div>
</div>

<div class="memory-section">
  <h2>🧠 Memory</h2>
  <input class="search-box" type="text" placeholder="Search memories..." id="memory-search" oninput="searchMemories()">
  <div id="memory-list" style="max-height:500px;overflow-y:auto;"></div>
</div>

<div class="modal-overlay" id="edit-modal">
  <div class="modal">
    <h3>✏️ Edit Memory</h3>
    <input type="hidden" id="edit-id">
    <textarea id="edit-content"></textarea>
    <div class="modal-row">
      <select id="edit-category">
        <option value="facts">facts</option>
        <option value="events">events</option>
        <option value="tasks">tasks</option>
        <option value="experience">experience</option>
        <option value="general">general</option>
      </select>
      <input type="number" id="edit-importance" min="1" max="10" placeholder="Importance 1-10">
    </div>
    <div class="modal-buttons">
      <button onclick="closeEditModal()">Cancel</button>
      <button class="save" onclick="saveMemory()">Save</button>
    </div>
  </div>
</div>

<script>
// ─── i18n ───
const i18n = {
  en: {
    loading: 'Loading...',
    running: 'Running', stopped: 'Stopped',
    terminal: 'Terminal', background: 'Background',
    logs: 'Logs',
    tunnelUrl: 'Tunnel URL', memories: 'Memories', todayLogs: "Today's Logs",
    notRunning: 'Not running',
    heatmapTitle: '📊 Interaction Heatmap',
    heatmapSub: 'Darker = more activity that day',
    less: 'Less', more: 'More',
    interactions: 'interactions', quietDay: 'quiet day',
    scheduledTasks: '⏰ Scheduled Tasks',
    noTasks: 'No scheduled tasks',
    remoteLog: '🔧 Remote Tool Log',
    remoteLogSub: 'Tool calls from Claude.ai chat',
    noRemote: 'No remote calls yet',
    memoryTitle: '🧠 Memory',
    searchPlaceholder: 'Search memories...',
    noMemories: 'No memories yet',
    edit: 'Edit', delete: 'Delete', cancel: 'Cancel', save: 'Save',
    editMemory: '✏️ Edit Memory',
    importance: 'Importance 1-10',
    confirmDelete: 'Delete this memory?',
    noData: 'No data',
    days: ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'],
    months: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
  },
  zh: {
    loading: '加载中...',
    running: '运行中', stopped: '已停止',
    terminal: '终端', background: '后台',
    logs: '日志',
    tunnelUrl: '隧道地址', memories: '记忆数', todayLogs: '今日日志',
    notRunning: '未运行',
    heatmapTitle: '📊 互动热力图',
    heatmapSub: '颜色越深 = 当天互动越多',
    less: '少', more: '多',
    interactions: '次互动', quietDay: '无互动',
    scheduledTasks: '⏰ 定时任务',
    noTasks: '暂无定时任务',
    remoteLog: '🔧 远程工具日志',
    remoteLogSub: '来自 Claude.ai chat 的工具调用',
    noRemote: '暂无远程调用',
    memoryTitle: '🧠 记忆库',
    searchPlaceholder: '搜索记忆...',
    noMemories: '暂无记忆',
    edit: '编辑', delete: '删除', cancel: '取消', save: '保存',
    editMemory: '✏️ 编辑记忆',
    importance: '重要性 1-10',
    confirmDelete: '确定删除这条记忆？',
    noData: '暂无数据',
    days: ['日','一','二','三','四','五','六'],
    months: ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],
  }
};
let lang = localStorage.getItem('imprint-lang') || 'en';
function t(key) { return i18n[lang][key] || i18n.en[key] || key; }
function toggleLang() {
  lang = lang === 'en' ? 'zh' : 'en';
  localStorage.setItem('imprint-lang', lang);
  document.getElementById('lang-label').textContent = lang === 'en' ? '中文' : 'EN';
  refreshAll();
}
function applyStaticI18n() {
  document.getElementById('lang-label').textContent = lang === 'en' ? '中文' : 'EN';
  document.querySelector('.heatmap-section h2').textContent = t('heatmapTitle');
  document.querySelector('.heatmap-section .heatmap-subtitle').textContent = t('heatmapSub');
  const legend = document.querySelectorAll('.heatmap-legend > span');
  if (legend.length >= 2) { legend[0].textContent = t('less'); legend[legend.length-1].textContent = t('more'); }
  const taskSections = document.querySelectorAll('.tasks-section h2');
  if (taskSections[0]) taskSections[0].textContent = t('scheduledTasks');
  if (taskSections[1]) taskSections[1].textContent = t('remoteLog');
  const remoteSub = document.querySelectorAll('.tasks-section .heatmap-subtitle');
  if (remoteSub[0]) remoteSub[0].textContent = t('remoteLogSub');
  document.querySelector('.memory-section h2').textContent = t('memoryTitle');
  document.getElementById('memory-search').placeholder = t('searchPlaceholder');
  document.querySelector('.modal h3').textContent = t('editMemory');
  document.getElementById('edit-importance').placeholder = t('importance');
  const modalBtns = document.querySelectorAll('.modal-buttons button');
  if (modalBtns[0]) modalBtns[0].textContent = t('cancel');
  if (modalBtns[1]) modalBtns[1].textContent = t('save');
  const infoLabels = document.querySelectorAll('.info-chip .label');
  if (infoLabels[0]) infoLabels[0].textContent = t('tunnelUrl');
  if (infoLabels[1]) infoLabels[1].textContent = t('memories');
  if (infoLabels[2]) infoLabels[2].textContent = t('todayLogs');
}
function refreshAll() {
  applyStaticI18n();
  fetchStatus();
  fetchHeatmap();
  searchMemories();
  fetchRemoteTools();
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    renderComponents(data.components);
    renderTasks(data.tasks || []);
    document.getElementById('tunnel-url').textContent = data.tunnel_url ? data.tunnel_url : t('notRunning');
    document.getElementById('memory-count').textContent = data.memory.count;
    document.getElementById('today-logs').textContent = data.memory.today_logs;
  } catch(e) {
    console.error(e);
  }
}

function renderComponents(components) {
  const grid = document.getElementById('components');
  let html = '';
  for (const [key, comp] of Object.entries(components)) {
    const dotClass = comp.running ? 'on' : 'off';
    const statusText = comp.running ? t('running') : t('stopped');
    const checked = comp.running ? 'checked' : '';
    const typeLabel = comp.type === 'terminal' ? t('terminal') : t('background');
    html += `
      <div class="card">
        <div class="card-header">
          <span>
            <span class="status-dot ${dotClass}"></span>
            <span class="card-name">${comp.name}</span>
          </span>
          <label class="toggle">
            <input type="checkbox" ${checked} onchange="toggleComponent('${key}', this.checked)">
            <span class="slider"></span>
          </label>
        </div>
        <div class="card-info">
          ${statusText} · ${typeLabel}${comp.pid ? ' · PID ' + comp.pid : ''}
          ${comp.type === 'background' ? '<br><button class="log-btn" onclick="toggleLog(\\'' + key + '\\')">' + t('logs') + '</button><div class="log-box" id="log-' + key + '"></div>' : ''}
        </div>
      </div>`;
  }
  grid.innerHTML = html;
}

function renderTasks(tasks) {
  const list = document.getElementById('tasks-list');
  if (!tasks.length) {
    list.innerHTML = '<div style="color:#B0AEA5;text-align:center;padding:12px">' + t('noTasks') + '</div>';
    return;
  }
  list.innerHTML = tasks.map(t => `
    <div class="task-item">
      <span class="task-dot"></span>
      <span>
        <span class="task-name">${t.name}</span>
        <div class="task-desc">${t.description}</div>
      </span>
    </div>
  `).join('');
}

async function toggleComponent(key, on) {
  const action = on ? 'start' : 'stop';
  await fetch(`/api/${key}/${action}`, { method: 'POST' });
  setTimeout(fetchStatus, 1500);
}

async function toggleLog(key) {
  const box = document.getElementById('log-' + key);
  if (box.style.display === 'block') {
    box.style.display = 'none';
    return;
  }
  const r = await fetch(`/api/logs/${key}`);
  const data = await r.json();
  box.textContent = data.logs;
  box.style.display = 'block';
  box.scrollTop = box.scrollHeight;
}

async function searchMemories() {
  const q = document.getElementById('memory-search').value;
  const r = await fetch(`/api/memories?q=${encodeURIComponent(q)}&limit=20`);
  const data = await r.json();
  renderMemories(data.memories);
}

let allMemories = [];
function renderMemories(memories) {
  allMemories = memories;
  const list = document.getElementById('memory-list');
  if (!memories.length) {
    list.innerHTML = '<div style="color:#666;padding:20px;text-align:center">' + t('noMemories') + '</div>';
    return;
  }
  list.innerHTML = memories.map(m => `
    <div class="memory-item">
      <div style="padding-right:80px;">${m.content.replace(/</g,'&lt;')}</div>
      <div class="memory-meta">[${m.category}|${m.source}] ${m.created_at} · importance ${m.importance}</div>
      <div class="memory-actions">
        <button onclick="openEditModal(${m.id})">${t('edit')}</button>
        <button class="del" onclick="deleteMemory(${m.id})">${t('delete')}</button>
      </div>
    </div>
  `).join('');
}

async function deleteMemory(id) {
  if (!confirm(t('confirmDelete'))) return;
  await fetch('/api/memories/' + id, {method: 'DELETE'});
  searchMemories();
}

function openEditModal(id) {
  const m = allMemories.find(x => x.id === id);
  if (!m) return;
  document.getElementById('edit-id').value = m.id;
  document.getElementById('edit-content').value = m.content;
  document.getElementById('edit-category').value = m.category;
  document.getElementById('edit-importance').value = m.importance;
  document.getElementById('edit-modal').classList.add('active');
}

function closeEditModal() {
  document.getElementById('edit-modal').classList.remove('active');
}

async function saveMemory() {
  const id = document.getElementById('edit-id').value;
  const body = {
    content: document.getElementById('edit-content').value,
    category: document.getElementById('edit-category').value,
    importance: parseInt(document.getElementById('edit-importance').value) || 5,
  };
  await fetch('/api/memories/' + id, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  closeEditModal();
  searchMemories();
}

async function fetchHeatmap() {
  try {
    const r = await fetch('/api/heatmap');
    const data = await r.json();
    renderHeatmap(data.days);
  } catch(e) { console.error(e); }
}

function renderHeatmap(days) {
  const container = document.getElementById('heatmap');
  if (!days || !days.length) {
    container.innerHTML = '<div style="color:#B0AEA5;text-align:center">' + t('noData') + '</div>';
    return;
  }

  // Level: 0=no activity, 1-4 by quartile
  const counts = days.map(d => d.count).filter(c => c > 0);
  const max = Math.max(...counts, 1);
  const q1 = max * 0.25, q2 = max * 0.5, q3 = max * 0.75;

  function level(c) {
    if (c === 0) return 0;
    if (c <= q1) return 1;
    if (c <= q2) return 2;
    if (c <= q3) return 3;
    return 4;
  }

  // GitHub-style: columns=weeks, rows=day-of-week
  const firstDate = new Date(days[0].date + 'T00:00:00');
  const firstDay = firstDate.getDay(); // 0=Sun

  // Pad first week
  const cells = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  days.forEach(d => cells.push(d));

  // Split into weeks
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }

  // Month labels
  const months = [];
  let lastMonth = '';
  weeks.forEach((week, wi) => {
    const realDay = week.find(d => d !== null);
    if (realDay) {
      const m = realDay.date.substring(0, 7);
      if (m !== lastMonth) {
        const monthNames = t('months');
        months.push({ index: wi, label: monthNames[parseInt(m.split('-')[1]) - 1] });
        lastMonth = m;
      }
    }
  });

  const dayLabels = t('days');

  const totalGridWidth = weeks.length * 15 - 3;
  let html = '<div class="heatmap-months" style="padding-left:32px;display:flex;width:' + totalGridWidth + 'px;">';
  // Position month labels
  let monthHtml = '';
  months.forEach((m, i) => {
    const next = months[i + 1] ? months[i + 1].index : weeks.length;
    const span = next - m.index;
    monthHtml += '<span style="width:' + (span * 15) + 'px;flex-shrink:0">' + m.label + '</span>';
  });
  html += monthHtml + '</div>';

  html += '<div class="heatmap-wrap">';
  // Day labels
  html += '<div class="heatmap-days">';
  for (let i = 0; i < 7; i++) {
    html += '<span>' + (i % 2 === 1 ? dayLabels[i] : '') + '</span>';
  }
  html += '</div>';

  // Grid cells
  html += '<div class="heatmap-grid">';
  weeks.forEach(week => {
    html += '<div class="heatmap-col">';
    for (let i = 0; i < 7; i++) {
      const d = i < week.length ? week[i] : null;
      if (d === null) {
        html += '<div class="heatmap-cell" style="visibility:hidden"></div>';
      } else {
        const lv = level(d.count);
        const tip = d.date + ': ' + (d.count > 0 ? d.count + ' ' + t('interactions') : t('quietDay'));
        html += '<div class="heatmap-cell" data-level="' + lv + '"><span class="tooltip">' + tip + '</span></div>';
      }
    }
    html += '</div>';
  });
  html += '</div></div>';

  container.innerHTML = html;
}

async function fetchRemoteTools() {
  try {
    const r = await fetch('/api/remote-tools');
    const data = await r.json();
    const el = document.getElementById('remote-tools');
    if (!data.tasks || !data.tasks.length) {
      el.innerHTML = '<div style="color:#B0AEA5">' + t('noRemote') + '</div>';
      return;
    }
    const icons = {pending:'⏳',running:'🔄',completed:'✅',error:'❌',timeout:'⏰'};
    let html = '<div style="display:flex;flex-direction:column;gap:8px;">';
    data.tasks.forEach(t => {
      const icon = icons[t.status] || '❓';
      const prompt = t.prompt.length > 60 ? t.prompt.substring(0,60)+'...' : t.prompt;
      const result = t.result ? (t.result.length > 120 ? t.result.substring(0,120)+'...' : t.result) : '';
      html += '<div style="background:#F5F4EF;padding:10px 14px;border-radius:8px;font-size:13px;">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
      html += '<span>' + icon + ' <strong>#' + t.id + '</strong> ' + prompt + '</span>';
      html += '<span style="color:#B0AEA5;font-size:11px;">' + (t.created_at||'') + '</span>';
      html += '</div>';
      if (result) {
        html += '<div style="margin-top:6px;color:#6B6962;font-size:12px;white-space:pre-wrap;max-height:120px;overflow-y:auto;">' + result.replace(/</g,'&lt;') + '</div>';
      }
      html += '</div>';
    });
    html += '</div>';
    el.innerHTML = html;
  } catch(e) { console.error(e); }
}

// Init
applyStaticI18n();
fetchStatus();
fetchHeatmap();
searchMemories();
fetchRemoteTools();
setInterval(fetchStatus, 3000);
setInterval(fetchRemoteTools, 10000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("✨ Claude Imprint Dashboard: http://localhost:3000", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=3000, log_level="warning")
