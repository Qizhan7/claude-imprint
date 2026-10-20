"""
Claude Imprint — Heartbeat Module

Two ways to wake up:

- channel (default when available): your Telegram `--channels` session runs
  inside tmux (start.sh does this). Each heartbeat pastes a short pulse into
  that same session, so the Claude that wakes up is the one you've been
  talking to: same context, and it answers through the Telegram reply tool.
  The official Telegram plugin is used as-is, nothing patched.
- headless (fallback): no tmux session found, so spawn a one-off `claude -p`
  with memory + send-only Telegram tools. Works, but it's a fresh instance
  with no conversation context.

HEARTBEAT_MODE=auto|channel|headless   (default auto)
HEARTBEAT_TMUX_TARGET=imprint-tg       (tmux session running the channel)
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import shutil
import subprocess
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

HEARTBEAT_MODE = os.environ.get("HEARTBEAT_MODE", "auto").lower()
TMUX_TARGET = os.environ.get("HEARTBEAT_TMUX_TARGET", "imprint-tg")
TMUX_BIN = shutil.which("tmux") or "tmux"
PULSE_MARK = "[Heartbeat"   # hooks/post_response_processor.py keys on this

# Paths to MCP server entry points
TELEGRAM_SERVER = PROJECT_DIR / "packages" / "imprint_telegram" / "server.py"


def _imprint_memory_cmd() -> str:
    """imprint-memory from the same venv as this process, else whatever is on PATH."""
    sibling = Path(sys.executable).parent / "imprint-memory"
    return str(sibling) if sibling.exists() else (shutil.which("imprint-memory") or "imprint-memory")


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
3. If notification needed, use the send_telegram tool{f' (chat_id {TELEGRAM_CHAT_ID})' if TELEGRAM_CHAT_ID else ''}
4. If there's new important information, save it to memory
5. If all clear, reply with HEARTBEAT_OK

Important: Don't send messages just to prove you're alive. Only notify when there's genuinely useful information.
"""
    return prompt


def build_pulse_text() -> str:
    """Short pulse for the live channel session. It already has CLAUDE.md,
    memory tools and the conversation, so only send what changes."""
    heartbeat_md = HEARTBEAT_FILE.read_text(encoding="utf-8") if HEARTBEAT_FILE.exists() else ""
    current_time = now_local().strftime("%Y-%m-%d %H:%M (%A)")
    where = f"the Telegram reply tool (chat_id {TELEGRAM_CHAT_ID})" if TELEGRAM_CHAT_ID else "the Telegram reply tool"
    quiet = "\nQuiet hours are on: only message them if it's urgent." if is_quiet_hours() else ""
    return f"""{PULSE_MARK} · {current_time}]
This is your scheduled heartbeat, not a message from the user. They only see what you send through {where}; what you write here stays in the terminal.{quiet}

{heartbeat_md.strip()}

If you want to reach them, send it. If there's nothing to do, answer HEARTBEAT_OK here."""


def _tmux(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([TMUX_BIN, *args], input=input_text, capture_output=True, text=True, timeout=10)


def channel_session_alive() -> bool:
    if not shutil.which(TMUX_BIN):
        return False
    try:
        return _tmux("has-session", "-t", TMUX_TARGET).returncode == 0
    except Exception:
        return False


# Anything that looks like Claude Code waiting on a choice. Pasting a pulse +
# Enter into one of these would answer it for the user, so skip that tick.
_DIALOG_HINTS = ("❯ 1. Yes", "Esc to cancel", "Enter to confirm", "Press Enter to continue")


def channel_session_blocked() -> str | None:
    try:
        pane = _tmux("capture-pane", "-p", "-t", TMUX_TARGET).stdout
    except Exception as e:
        return f"capture failed: {e}"
    tail = "\n".join(pane.rstrip().splitlines()[-15:])
    for hint in _DIALOG_HINTS:
        if hint in tail:
            return hint
    return None


async def run_channel_pulse() -> bool:
    """Paste one pulse into the tmux-hosted channel session. True if sent."""
    ts = now_local().strftime('%H:%M:%S')
    blocked = channel_session_blocked()
    if blocked:
        print(f"[{ts}] Pulse skipped: session is waiting on a prompt ({blocked!r})")
        return False
    text = build_pulse_text()
    buf = "imprint-pulse"
    r = _tmux("load-buffer", "-b", buf, "-", input_text=text)
    if r.returncode != 0:
        print(f"[{ts}] Pulse failed (load-buffer): {r.stderr.strip()}")
        return False
    # -p: bracketed paste, so the newlines land in one message instead of
    # submitting line by line. Enter goes separately once the paste settles.
    r = _tmux("paste-buffer", "-p", "-d", "-b", buf, "-t", TMUX_TARGET)
    if r.returncode != 0:
        print(f"[{ts}] Pulse failed (paste-buffer): {r.stderr.strip()}")
        return False
    await asyncio.sleep(0.8)
    _tmux("send-keys", "-t", TMUX_TARGET, "Enter")
    print(f"[{ts}] Pulse → tmux:{TMUX_TARGET}")
    return True


async def run_heartbeat():
    """One heartbeat: into the live channel session if there is one."""
    use_channel = HEARTBEAT_MODE == "channel" or (HEARTBEAT_MODE == "auto" and channel_session_alive())
    if use_channel:
        if not channel_session_alive():
            ts = now_local().strftime('%H:%M:%S')
            print(f"[{ts}] Pulse skipped: tmux session {TMUX_TARGET!r} not running (start.sh starts it)")
            return
        await run_channel_pulse()
        return
    await run_headless()


async def run_headless():
    """Fallback: one-off `claude -p` with memory + send-only Telegram tools."""
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
    # Send-only Telegram server. Don't load the official Telegram channel
    # plugin here: it polls getUpdates, and Telegram allows one poller per bot
    # token, so it would fight (or kill) your --channels session.
    mcp_servers = {
        "imprint-memory": {
            "command": _imprint_memory_cmd(),
            "args": []
        },
    }
    if TELEGRAM_SERVER.exists():
        mcp_servers["imprint-telegram"] = {
            "command": sys.executable,
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
    print(f"  Mode: {HEARTBEAT_MODE} (tmux target: {TMUX_TARGET}, alive: {channel_session_alive()})")
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
