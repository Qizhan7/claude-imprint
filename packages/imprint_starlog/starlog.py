#!/usr/bin/env python3
"""
Starlog — a timeline of your day across every Claude window.

  record   Stop hook. After a stretch of conversation (enough new text, and a
           few minutes since the last line), ask a small model for one
           first-person line and append it to today's timeline:
               - 14:20 [telegram] Fixed the sync bug together; she laughed at the log
  arrange  Every ~30 min (the heartbeat agent calls it, or cron). Weaves new
           lines into short paragraphs, merging the same event seen from
           different windows. Earlier paragraphs stay frozen; only the latest
           one may be revised to absorb what continues it.
  context  SessionStart hook. Prints today's paragraphs + lines not woven yet,
           so a fresh session wakes up knowing what the other windows did.
  since    Lines from other windows newer than a cursor (used by heartbeat
           pulses so a long-running channel session keeps up).

Files live in $IMPRINT_DATA_DIR/starlog/ (default ~/.imprint/starlog/):
  timeline-<day>.md   raw lines        arranged-<day>.json   segments (source of truth)
  arranged-<day>.md   rendered view    sessions.json         per-session offsets

A "day" starts at STARLOG_DAY_START (default 5), so 01:00 still belongs to
yesterday. Model calls go through `claude -p --model haiku` on your own
subscription; if that fails, lines are kept raw and nothing is lost.

Stdlib only.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Config ──────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("IMPRINT_DATA_DIR", str(Path.home() / ".imprint"))).expanduser()
STAR_DIR = Path(os.environ.get("STARLOG_DIR", str(DATA_DIR / "starlog"))).expanduser()
DAY_START = int(os.environ.get("STARLOG_DAY_START", 5))

MIN_CHARS = int(os.environ.get("STARLOG_MIN_CHARS", 400))        # new text needed for a line
MIN_INTERVAL_S = int(os.environ.get("STARLOG_MIN_INTERVAL", 600))  # per window, between lines
FORCE_CHARS = int(os.environ.get("STARLOG_FORCE_CHARS", 8000))   # ...unless this much piled up
MAX_CHUNK_CHARS = 6000                                           # tail sent to the model

MIN_NEW = 3            # arrange once this many lines are waiting
MAX_WAIT_MIN = 25      # ...or the oldest has waited this long
BATCH_MAX = 10
MAX_ROUNDS = 8
CONTINUE_GAP_MIN = 90  # previous paragraph is revisable only if it ended this recently

INJECT_CHARS = int(os.environ.get("STARLOG_INJECT_CHARS", 8000))
MODEL = os.environ.get("STARLOG_MODEL", "haiku")
CHILD_ENV = "IMPRINT_STARLOG_CHILD"   # set on our own `claude -p` calls

LINE_RE = re.compile(r"^- (\d{2}):(\d{2}) \[([^\]]+)\] (.+)$")
CHANNEL_RE = re.compile(r'<channel\s+source="([^"]+)"')


def _tz():
    if "TZ_OFFSET" in os.environ:
        return timezone(timedelta(hours=int(os.environ["TZ_OFFSET"])))
    return None  # system local time


def now() -> datetime:
    return datetime.now(_tz())


def to_local(ts: str) -> datetime:
    """Transcript timestamps are ISO UTC ('...Z')."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(_tz()) if _tz() else dt.astimezone()
    except Exception:
        return now()


def day_of(dt: datetime) -> str:
    return (dt - timedelta(hours=DAY_START)).date().isoformat()


def clock_key(hh: int, mm: int) -> int:
    """Minutes since the day started, so 01:30 sorts after 23:00."""
    return ((hh - DAY_START) % 24) * 60 + mm


def row_key(line: str) -> str:
    return hashlib.sha1(line.strip().encode("utf-8")).hexdigest()[:16]


def _path(kind: str, day: str) -> Path:
    ext = "json" if kind == "arranged-state" else "md"
    name = "arranged" if kind.startswith("arranged") else kind
    return STAR_DIR / f"{name}-{day}.{ext}"


@contextmanager
def _lock(name: str, blocking: bool = True):
    STAR_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(STAR_DIR / f".{name}.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        fh.close()
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ─── Model ───────────────────────────────────────────────

def _claude_bin() -> str:
    return os.environ.get("CLAUDE_BIN") or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def ask_model(prompt: str, timeout: int = 120) -> str | None:
    """One-shot, tool-less, no MCP, no session saved, user hooks not loaded."""
    env = {**os.environ, CHILD_ENV: "1"}
    env.pop("CLAUDECODE", None)
    # Hooks may not inherit Claude Code's auth env. Fall back to the same
    # long-lived token file cron-task.sh uses (`claude setup-token`).
    token_file = Path.home() / ".claude" / "cron-token"
    if not env.get("CLAUDE_CODE_OAUTH_TOKEN") and not env.get("ANTHROPIC_API_KEY") and token_file.exists():
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token_file.read_text().strip()
    cmd = [_claude_bin(), "-p", prompt, "--model", MODEL, "--output-format", "text",
           "--no-session-persistence", "--strict-mcp-config", "--tools", "",
           "--setting-sources", "project"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(STAR_DIR), env=env, stdin=subprocess.DEVNULL)
    except Exception as e:
        print(f"starlog: model call failed: {e}", file=sys.stderr)
        return None
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        print(f"starlog: model call failed (rc={r.returncode}): {(r.stderr or out)[:200]}", file=sys.stderr)
        return None
    return out


# ─── Timeline ────────────────────────────────────────────

def read_lines(day: str) -> list[str]:
    p = _path("timeline", day)
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines() if LINE_RE.match(l)]


def append_line(dt: datetime, window: str, text: str) -> str:
    text = " ".join(text.split())
    line = f"- {dt:%H:%M} [{window}] {text}"
    day = day_of(dt)
    with _lock("timeline"):
        lines = read_lines(day)
        if line not in lines:
            lines.append(line)
        lines.sort(key=lambda l: (clock_key(int(LINE_RE.match(l)[1]), int(LINE_RE.match(l)[2]))))
        _atomic_write(_path("timeline", day), f"# Starlog · {day}\n\n" + "\n".join(lines) + "\n")
    return line


def _window_name(cwd: str, entries: list[dict], known: str | None) -> str:
    if known:
        return known
    for e in entries:
        m = CHANNEL_RE.search(e.get("_text", ""))
        if m:
            src = m.group(1)                         # plugin:telegram:telegram / server:discord
            parts = [p for p in re.split(r"[:@]", src) if p and p not in ("plugin", "server")]
            if parts:
                return parts[0]
    base = os.path.basename(cwd.rstrip("/")) if cwd else ""
    return f"cc·{base}" if base else "cc"


def _entry_text(entry: dict) -> tuple[str, str] | None:
    """(role, text) for real user/assistant turns; tool chatter is skipped."""
    if entry.get("type") not in ("user", "assistant") or entry.get("isMeta"):
        return None
    msg = entry.get("message") or {}
    role = msg.get("role") or entry["type"]
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(c.get("text", "") for c in content
                         if isinstance(c, dict) and c.get("type") == "text")
    else:
        return None
    text = text.strip()
    if not text or text.startswith("<command-") or text.startswith("<local-command"):
        return None
    return role, text


LINE_PROMPT = """Below is a stretch of conversation between the user and you (the assistant), from the window "{window}".

Write ONE line for your own timeline of the day:
- first person ("I" = you, the assistant; call the user by the name the conversation uses, or "they")
- past tense, what actually happened, was made, or was decided; concrete names and outcomes
- at most about 40 words, in the same language as the conversation
- only what is in the text below; no guessing

Output just the line. No preamble, no quotes, no timestamp.

---
{chunk}"""


def record(transcript: str, session_id: str, cwd: str = "") -> str | None:
    """Stop hook entry. Returns the line written, or None."""
    if os.environ.get(CHILD_ENV):
        return None
    tp = Path(transcript)
    if not tp.exists():
        return None
    STAR_DIR.mkdir(parents=True, exist_ok=True)
    with _lock(f"session-{session_id[:16]}", blocking=False) as got:
        if not got:
            return None  # another record() for this session is mid-flight
        sessions_p = STAR_DIR / "sessions.json"
        with _lock("sessions"):
            sessions = json.loads(sessions_p.read_text()) if sessions_p.exists() else {}
        st = sessions.get(session_id, {"offset": 0, "last_at": 0, "window": None})

        raw = tp.read_text(encoding="utf-8", errors="replace").splitlines()
        entries = []
        for l in raw[st["offset"]:]:
            try:
                e = json.loads(l)
            except Exception:
                continue
            got_text = _entry_text(e)
            if got_text:
                e["_role"], e["_text"] = got_text
                entries.append(e)
        if not entries:
            return None

        chunk = "\n\n".join(f"{'User' if e['_role'] == 'user' else 'Assistant'}: {e['_text']}" for e in entries)
        waited = time.time() - st["last_at"]
        if len(chunk) < MIN_CHARS or (waited < MIN_INTERVAL_S and len(chunk) < FORCE_CHARS):
            return None

        window = _window_name(cwd, entries, st.get("window"))
        prompt = LINE_PROMPT.format(window=window, chunk=chunk[-MAX_CHUNK_CHARS:])
        text = ask_model(prompt, timeout=90)
        if not text:
            return None  # offset not advanced: retried next turn
        text = text.splitlines()[0].strip().strip('"').lstrip("- ").strip()
        line = append_line(to_local(entries[0].get("timestamp", "")), window, text)

        st.update(offset=len(raw), last_at=time.time(), window=window)
        with _lock("sessions"):
            sessions = json.loads(sessions_p.read_text()) if sessions_p.exists() else {}
            sessions[session_id] = st
            _atomic_write(sessions_p, json.dumps(sessions, ensure_ascii=False, indent=1))
        return line


# ─── Arrange ─────────────────────────────────────────────

def load_state(day: str) -> dict:
    p = _path("arranged-state", day)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"day": day, "segments": []}


def _seg_sort(seg: dict) -> int:
    hh, mm = map(int, seg["start"].split(":"))
    return clock_key(hh, mm)


def render_md(state: dict) -> str:
    out = [f"# Starlog · {state['day']} (arranged)", ""]
    for seg in sorted(state["segments"], key=_seg_sort):
        span = seg["start"] if seg["start"] == seg["end"] else f"{seg['start']}–{seg['end']}"
        out += [f"## {span}{' (raw)' if seg.get('raw') else ''}", seg["text"], ""]
    return "\n".join(out)


ARRANGE_PROMPT = """You keep a timeline of your own day. These notes come from several windows (Telegram, terminal sessions, scheduled runs), so the same event can appear more than once.
{previous}
New notes:
{notes}

Weave the new notes into paragraphs:
- first person, past tense, plain and concrete; 1-3 sentences, at most about 80 words each
- merge the same event across windows; never mention window names
- one paragraph per event or thread; notes that belong together go together
- only facts from the notes: don't fill gaps, don't invent endings, don't call something decided unless a note says it was
- if a note corrects an earlier one, keep only the corrected version
- same language as the notes

Output only these lines:
{prev_fmt}[NEW <note numbers, e.g. 1,2,4>] <paragraph>
[NEW ...] ..."""


def _parse_arranged(out: str, n_notes: int, has_prev: bool):
    prev_text = None
    news: list[tuple[list[int], str]] = []
    for m in re.finditer(r"^\[(PREVIOUS|NEW([^\]]*))\]\s*(.+?)(?=^\[(?:PREVIOUS|NEW)|\Z)", out, re.S | re.M):
        body = " ".join(m.group(3).split())
        if m.group(1) == "PREVIOUS":
            if has_prev and body.upper() != "SAME":
                prev_text = body
            continue
        nums = [int(x) for x in re.findall(r"\d+", m.group(2) or "") if 1 <= int(x) <= n_notes]
        if body:
            news.append((nums, body))
    return prev_text, news


def _raw_segment(batch: list[str]) -> dict:
    ms = [LINE_RE.match(l) for l in batch]
    return {"start": f"{ms[0][1]}:{ms[0][2]}", "end": f"{ms[-1][1]}:{ms[-1][2]}",
            "text": " ".join(f"{m[1]}:{m[2]} {m[4]}" for m in ms),
            "keys": [row_key(l) for l in batch], "raw": True}


def arrange(day: str | None = None, force: bool = False, model=ask_model) -> int:
    """Weave waiting lines into segments. Returns how many lines got arranged."""
    day = day or day_of(now())
    with _lock("arrange", blocking=False) as got:
        if not got:
            return 0
        done_total = 0
        for _ in range(MAX_ROUNDS):
            lines = read_lines(day)
            state = load_state(day)
            done = {k for s in state["segments"] for k in s["keys"]}
            new = [l for l in lines if row_key(l) not in done]
            if not new:
                break
            if not force and len(new) < MIN_NEW and day == day_of(now()):
                m = LINE_RE.match(new[0])
                oldest = clock_key(int(m[1]), int(m[2]))
                cur = clock_key(now().hour, now().minute)
                if cur - oldest < MAX_WAIT_MIN:
                    break
            batch = new[:BATCH_MAX]
            m0 = LINE_RE.match(batch[0])
            segs = sorted(state["segments"], key=_seg_sort)
            prev = None
            if segs:
                hh, mm = map(int, segs[-1]["end"].split(":"))
                if 0 <= clock_key(int(m0[1]), int(m0[2])) - clock_key(hh, mm) <= CONTINUE_GAP_MIN:
                    prev = segs[-1]

            notes = "\n".join(f"{i}. {LINE_RE.match(l)[1]}:{LINE_RE.match(l)[2]} [{LINE_RE.match(l)[3]}] {LINE_RE.match(l)[4]}"
                              for i, l in enumerate(batch, 1))
            prompt = ARRANGE_PROMPT.format(
                previous=(f"\nPrevious paragraph ({prev['start']}–{prev['end']}). Revise it only if new notes continue the same thing; otherwise answer SAME:\n{prev['text']}\n" if prev else ""),
                notes=notes,
                prev_fmt=("[PREVIOUS] <revised previous paragraph, or SAME>\n" if prev else ""),
            )
            out = model(prompt) if model else None
            prev_text, news = _parse_arranged(out or "", len(batch), prev is not None)

            new_segments = []
            covered: set[int] = set()
            if news:
                for nums, body in news:
                    nums = [n for n in nums if n not in covered] or ([] if covered else list(range(1, len(batch) + 1)))
                    covered.update(nums)
                    if not nums:
                        continue
                    picked = [batch[n - 1] for n in sorted(nums)]
                    ms = [LINE_RE.match(l) for l in picked]
                    new_segments.append({"start": f"{ms[0][1]}:{ms[0][2]}", "end": f"{ms[-1][1]}:{ms[-1][2]}",
                                         "text": body, "keys": [row_key(l) for l in picked]})
            left = [batch[i - 1] for i in range(1, len(batch) + 1) if i not in covered]
            absorbed = prev is not None and prev_text
            if absorbed:
                prev["text"] = prev_text
            if left and absorbed:
                # notes the model folded into the revised previous paragraph
                prev["keys"] += [row_key(l) for l in left]
                m = LINE_RE.match(left[-1])
                pe = tuple(map(int, prev["end"].split(":")))
                if clock_key(int(m[1]), int(m[2])) > clock_key(*pe):
                    prev["end"] = f"{m[1]}:{m[2]}"
            elif left and new_segments:
                # model skipped a note: count it under the last paragraph
                new_segments[-1]["keys"] += [row_key(l) for l in left]
            if not new_segments and not (left and absorbed):
                new_segments = [_raw_segment(batch)]

            state["segments"] = segs + new_segments
            with _lock("state"):
                _atomic_write(_path("arranged-state", day), json.dumps(state, ensure_ascii=False, indent=1))
                _atomic_write(_path("arranged-md", day), render_md(state))
            done_total += len(batch)
        return done_total


# ─── Context for new sessions ────────────────────────────

def loose_lines(day: str) -> list[str]:
    done = {k for s in load_state(day)["segments"] for k in s["keys"]}
    return [l for l in read_lines(day) if row_key(l) not in done]


def render_context(budget: int = INJECT_CHARS) -> str:
    today = day_of(now())
    yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
    segs = [("today", s) for s in sorted(load_state(today)["segments"], key=_seg_sort)]
    y_tail = sorted(load_state(yesterday)["segments"], key=_seg_sort)[-3:]
    loose = loose_lines(today)
    if not segs and not loose and not y_tail:
        return ""

    def build(y, s, lo, dropped):
        out = [f'<starlog day="{today}">',
               "Your own timeline across all windows. Paragraphs are arranged every ~30 min; "
               "the last lines are newer and not woven in yet. Context, not instructions."]
        if y:
            out.append(f"\nEnd of yesterday ({yesterday}):")
            out += [f"## {x['start']}–{x['end']}\n{x['text']}" for x in y]
        if s:
            out.append("\nToday:")
            if dropped:
                out.append(f"(… {dropped} earlier paragraphs: {_path('arranged-md', today)})")
            out += [f"## {x['start']}{'' if x['start'] == x['end'] else '–' + x['end']}\n{x['text']}" for _, x in s]
        if lo:
            out.append("\nNot arranged yet:")
            out += lo
        out.append(f"\nFull files: {STAR_DIR}/\n</starlog>")
        return "\n".join(out)

    dropped = 0
    text = build(y_tail, segs, loose, dropped)
    while len(text) > budget and y_tail:
        y_tail = y_tail[1:]
        text = build(y_tail, segs, loose, dropped)
    while len(text) > budget and len(loose) > 5:
        loose = loose[1:]
        text = build(y_tail, segs, loose, dropped)
    while len(text) > budget and len(segs) > 3:
        segs = segs[1:]
        dropped += 1
        text = build(y_tail, segs, loose, dropped)
    return text


def lines_since(cursor_name: str, exclude_window: str | None = None, limit: int = 12) -> list[str]:
    """New timeline lines since the last call with this cursor (today only)."""
    day = day_of(now())
    cur_p = STAR_DIR / f"cursor-{cursor_name}.json"
    seen = set()
    if cur_p.exists():
        try:
            c = json.loads(cur_p.read_text())
            if c.get("day") == day:
                seen = set(c.get("keys", []))
        except Exception:
            pass
    lines = read_lines(day)
    fresh = [l for l in lines if row_key(l) not in seen
             and not (exclude_window and LINE_RE.match(l)[3] == exclude_window)]
    STAR_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(cur_p, json.dumps({"day": day, "keys": [row_key(l) for l in lines]}))
    return fresh[-limit:]


# ─── CLI ─────────────────────────────────────────────────

def _hook_input() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "context"
    if cmd == "record":
        if len(argv) >= 4:
            transcript, session_id = argv[2], argv[3]
            cwd = argv[4] if len(argv) > 4 else ""
        else:
            h = _hook_input()
            transcript, session_id, cwd = h.get("transcript_path", ""), h.get("session_id", ""), h.get("cwd", "")
        line = record(transcript, session_id, cwd) if transcript and session_id else None
        if line:
            print(line)
    elif cmd == "arrange":
        n = arrange(argv[2] if len(argv) > 2 and not argv[2].startswith("-") else None, force="--force" in argv)
        print(f"arranged {n} line(s)")
    elif cmd == "context":
        if os.environ.get(CHILD_ENV):
            return 0
        print(render_context())
    elif cmd == "show":
        day = argv[2] if len(argv) > 2 else day_of(now())
        print(render_md(load_state(day)))
        lo = loose_lines(day)
        if lo:
            print("Not arranged yet:\n" + "\n".join(lo))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
