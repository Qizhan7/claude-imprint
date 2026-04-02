"""
Claude Imprint — Heartbeat Module
Periodically invokes Claude Code CLI to perform automated checks.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Config ──────────────────────────────────────────────

TZ_OFFSET = int(os.environ.get("TZ_OFFSET", 0))
LOCAL_TZ = timezone(timedelta(hours=TZ_OFFSET))

PACKAGE_DIR = Path(__file__).parent
PROJECT_DIR = PACKAGE_DIR.parent.parent  # packages/imprint_heartbeat -> project root
DATA_DIR = Path(os.environ.get("IMPRINT_DATA_DIR", str(Path.home() / ".imprint")))

GLOBAL_CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
HEARTBEAT_FILE = PACKAGE_DIR / "HEARTBEAT.md"
MEMORY_INDEX = DATA_DIR / "MEMORY.md"

CLAUDE_BIN = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")

HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", 900))
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
QUIET_START = int(os.environ.get("QUIET_START", 23))
QUIET_END = int(os.environ.get("QUIET_END", 7))

HEARTBEAT_SESSION_FILE = PROJECT_DIR / "data" / "heartbeat_session.txt"

# Paths to MCP server entry points
TELEGRAM_SERVER = PROJECT_DIR / "packages" / "imprint_telegram" / "server.py"


def _get_telegram_plugin_dir() -> Path:
    """Find the latest installed Telegram plugin version."""
    base = Path.home() / ".claude/plugins/cache/claude-plugins-official/telegram"
    if base.exists():
        versions = sorted(base.iterdir(), reverse=True)
        if versions:
            return versions[0]
    return base / "0.0.1"


def now_local():
    return datetime.now(LOCAL_TZ)


def is_quiet_hours():
    hour = now_local().hour
    return hour >= QUIET_START or hour < QUIET_END


def load_session_id() -> str | None:
    if HEARTBEAT_SESSION_FILE.exists():
        return HEARTBEAT_SESSION_FILE.read_text().strip()
    return None


def save_session_id(sid: str):
    HEARTBEAT_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_SESSION_FILE.write_text(sid)


def build_heartbeat_prompt() -> str:
    """Build heartbeat prompt with personality + rules + memory + checklist"""
    claude_md = GLOBAL_CLAUDE_MD.read_text(encoding="utf-8") if GLOBAL_CLAUDE_MD.exists() else ""
    heartbeat_md = HEARTBEAT_FILE.read_text(encoding="utf-8") if HEARTBEAT_FILE.exists() else ""
    memory_ctx = MEMORY_INDEX.read_text(encoding="utf-8") if MEMORY_INDEX.exists() else "(No memory index)"
    current_time = now_local().strftime("%Y-%m-%d %H:%M (%A)")
    quiet = is_quiet_hours()

    prompt = f"""You are executing a scheduled heartbeat check.

Current time: {current_time}
{"WARNING: Quiet hours active. Do not send messages unless urgent." if quiet else ""}

## Identity and Rules
{claude_md}

## Memory
{memory_ctx}

## Heartbeat Checklist
{heartbeat_md}

## Instructions
1. Go through the heartbeat checklist
2. Decide if any action or notification is needed
3. If notification needed, use Telegram reply tool{f' (chat_id {TELEGRAM_CHAT_ID})' if TELEGRAM_CHAT_ID else ''}
4. If there's new important information, save it to memory
5. If all clear, reply with HEARTBEAT_OK

Important: Don't send messages just to prove you're alive. Only notify when there's genuinely useful information.
"""
    return prompt


async def run_heartbeat():
    """Execute one heartbeat cycle"""
    prompt = build_heartbeat_prompt()
    session_id = load_session_id()

    cmd = [
        CLAUDE_BIN,
        "-p", prompt,
        "--output-format", "json",
        "--max-budget-usd", "0.50",
    ]

    if session_id:
        cmd.extend(["--resume", session_id])

    # Build MCP config with modular servers
    mcp_servers = {
        "telegram": {
            "command": "bun",
            "args": ["run", "--cwd",
                     str(_get_telegram_plugin_dir()),
                     "--shell=bun", "--silent", "start"]
        },
        "imprint-memory": {
            "command": "imprint-memory",
            "args": []
        },
    }
    # Add telegram send server if available
    if TELEGRAM_SERVER.exists():
        mcp_servers["imprint-telegram"] = {
            "command": "python3",
            "args": [str(TELEGRAM_SERVER)]
        }

    mcp_config = json.dumps({"mcpServers": mcp_servers})
    cmd.extend(["--mcp-config", mcp_config])
    cmd.extend(["--permission-mode", "auto"])

    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    env["PATH"] = os.path.expanduser("~/.local/bin") + ":" + \
                  os.path.expanduser("~/.bun/bin") + ":" + \
                  env.get("PATH", "")

    ts = now_local().strftime('%H:%M:%S')
    print(f"[{ts}] Heartbeat starting...")

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_DIR),
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=300,
        )

        output = stdout.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            print(f"[{ts}] Heartbeat failed: {err[:200]}")
            return

        try:
            result = json.loads(output)
            new_session_id = result.get("session_id")
            if new_session_id:
                save_session_id(new_session_id)

            response_text = result.get("result", "")
            if "HEARTBEAT_OK" in response_text:
                print(f"[{ts}] Heartbeat OK")
            else:
                print(f"[{ts}] Heartbeat: action taken")
        except json.JSONDecodeError:
            if "HEARTBEAT_OK" in output:
                print(f"[{ts}] Heartbeat OK")
            else:
                print(f"[{ts}] Heartbeat output: {output[:200]}")

    except asyncio.TimeoutError:
        print(f"[{ts}] Heartbeat timeout (5min)")
        if proc:
            proc.kill()
    except Exception as e:
        print(f"[{ts}] Heartbeat error: {e}")


async def heartbeat_loop():
    print(f"Heartbeat agent started")
    print(f"  Interval: {HEARTBEAT_INTERVAL}s ({HEARTBEAT_INTERVAL // 60}min)")
    print(f"  Project: {PROJECT_DIR}")
    print()

    while True:
        try:
            await run_heartbeat()
        except Exception as e:
            print(f"Heartbeat loop error: {e}")

        await asyncio.sleep(HEARTBEAT_INTERVAL)


def main():
    loop = asyncio.new_event_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: sys.exit(0))

    try:
        loop.run_until_complete(heartbeat_loop())
    except (KeyboardInterrupt, SystemExit):
        print("\nHeartbeat stopped")


if __name__ == "__main__":
    main()
