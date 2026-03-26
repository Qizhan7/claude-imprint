"""
Claude Imprint — Memory System
SQLite + FTS5 + Ollama bge-m3 vector embeddings, hybrid search.

Architecture:
- SQLite single-file storage (memories + vectors + FTS index)
- Hybrid search (vector semantic + FTS5 keyword + time decay)
- MCP tool + Python module dual interface
"""

import json
import math
import os
import sqlite3
import struct
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ─── Config ──────────────────────────────────────────────
TZ_OFFSET = int(os.environ.get("TZ_OFFSET", 0))
LOCAL_TZ = timezone(timedelta(hours=TZ_OFFSET))
PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "memory.db"
DAILY_LOG_DIR = PROJECT_DIR / "memory"
BANK_DIR = PROJECT_DIR / "memory" / "bank"
MEMORY_INDEX = PROJECT_DIR / "MEMORY.md"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
EMBED_DIM = 1024  # bge-m3 output dimension

# Hybrid search weights
WEIGHT_VECTOR = 0.4   # Semantic similarity
WEIGHT_FTS = 0.4      # Keyword match
WEIGHT_RECENCY = 0.2  # Time decay

# ─── Database Init ───────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    """Get database connection, auto-create tables"""
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.row_factory = sqlite3.Row
    _init_tables(db)
    return db


def _init_tables(db: sqlite3.Connection):
    """Create tables (idempotent)"""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            source TEXT DEFAULT 'cc',
            tags TEXT DEFAULT '[]',
            importance INTEGER DEFAULT 5,
            recalled_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS memory_vectors (
            memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL,
            model TEXT DEFAULT 'bge-m3'
        );

        CREATE TABLE IF NOT EXISTS daily_logs (
            date TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            summary TEXT,
            embedding BLOB
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bank_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding BLOB,
            file_mtime REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cc_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            result TEXT,
            source TEXT DEFAULT 'chat',
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS message_bus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            direction TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)

    # FTS5 full-text index
    try:
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(content, category, tags, content=memories, content_rowid=id)
        """)
    except sqlite3.OperationalError:
        pass

    # FTS5 sync triggers
    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, content, category, tags)
            VALUES (new.id, new.content, new.category, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category, tags)
            VALUES ('delete', old.id, old.content, old.category, old.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, content, category, tags)
            VALUES ('delete', old.id, old.content, old.category, old.tags);
            INSERT INTO memories_fts(rowid, content, category, tags)
            VALUES (new.id, new.content, new.category, new.tags);
        END;
    """)
    db.commit()


# ─── Vector Embeddings ───────────────────────────────────

def _embed(text: str) -> Optional[list[float]]:
    """Call Ollama to generate embedding vector. Returns None on failure."""
    try:
        payload = json.dumps({"model": EMBED_MODEL, "input": text}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            embeddings = data.get("embeddings", [])
            if embeddings and len(embeddings[0]) == EMBED_DIM:
                return embeddings[0]
    except Exception:
        pass  # Ollama not running — fall back to keyword-only search
    return None


def _vec_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_vec(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─── Time Utils ──────────────────────────────────────────

def _now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def _now_str() -> str:
    return _now_local().strftime("%Y-%m-%d %H:%M")


def _recency_score(created_at: str) -> float:
    """Time decay score: more recent = higher (0-1). 30-day half-life."""
    try:
        t = datetime.strptime(created_at, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
        days_ago = (_now_local() - t).total_seconds() / 86400
        return math.exp(-days_ago / 30)
    except (ValueError, TypeError):
        return 0.5


# ─── Core API ────────────────────────────────────────────

def remember(content: str, category: str = "general", source: str = "cc",
             tags: Optional[list[str]] = None, importance: int = 5) -> str:
    """Store a memory"""
    db = _get_db()

    # Dedup: skip if exact same content exists
    existing = db.execute(
        "SELECT id FROM memories WHERE content = ?", (content,)
    ).fetchone()
    if existing:
        db.close()
        return "Duplicate memory, skipped"

    tags_json = json.dumps(tags or [], ensure_ascii=False)
    now = _now_str()

    cursor = db.execute(
        """INSERT INTO memories (content, category, source, tags, importance, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (content, category, source, tags_json, importance, now),
    )
    memory_id = cursor.lastrowid

    vec = _embed(content)
    if vec:
        db.execute(
            "INSERT INTO memory_vectors (memory_id, embedding, model) VALUES (?, ?, ?)",
            (memory_id, _vec_to_blob(vec), EMBED_MODEL),
        )

    db.commit()
    db.close()
    _rebuild_index()
    return f"Remembered [{category}]: {content[:50]}..."


def forget(keyword: str) -> str:
    """Delete memories containing keyword"""
    db = _get_db()
    rows = db.execute(
        "SELECT id, content FROM memories WHERE content LIKE ?",
        (f"%{keyword}%",),
    ).fetchall()

    if not rows:
        db.close()
        return f"No memories found containing '{keyword}'"

    for row in rows:
        db.execute("DELETE FROM memory_vectors WHERE memory_id = ?", (row["id"],))
        db.execute("DELETE FROM memories WHERE id = ?", (row["id"],))

    db.commit()
    db.close()
    _rebuild_index()
    return f"Deleted {len(rows)} memories containing '{keyword}'"


def search(query: str, limit: int = 10, category: Optional[str] = None) -> list[dict]:
    """Hybrid search: vector semantic + FTS5 keyword + time decay"""
    db = _get_db()
    results = {}

    # --- 1. FTS5 keyword search ---
    try:
        fts_query = query.replace('"', '""')
        cat_filter = "AND m.category = ?" if category else ""
        params = [fts_query, category] if category else [fts_query]
        fts_rows = db.execute(f"""
            SELECT m.id, m.content, m.category, m.source, m.importance,
                   m.created_at, m.recalled_count,
                   rank
            FROM memories_fts f
            JOIN memories m ON f.rowid = m.id
            WHERE memories_fts MATCH ? {cat_filter}
            ORDER BY rank
            LIMIT {limit * 2}
        """, params).fetchall()

        if fts_rows:
            max_rank = max(abs(r["rank"]) for r in fts_rows) or 1
            for r in fts_rows:
                mid = r["id"]
                fts_score = abs(r["rank"]) / max_rank
                results[mid] = {
                    "id": mid,
                    "content": r["content"],
                    "category": r["category"],
                    "source": r["source"],
                    "importance": r["importance"],
                    "created_at": r["created_at"],
                    "recalled_count": r["recalled_count"],
                    "fts_score": fts_score,
                    "vec_score": 0.0,
                }
    except sqlite3.OperationalError:
        pass

    # --- 2. Vector semantic search ---
    query_vec = _embed(query)
    if query_vec:
        cat_filter = "AND m.category = ?" if category else ""
        params = [category] if category else []
        vec_rows = db.execute(f"""
            SELECT m.id, m.content, m.category, m.source, m.importance,
                   m.created_at, m.recalled_count,
                   v.embedding
            FROM memories m
            JOIN memory_vectors v ON m.id = v.memory_id
            WHERE 1=1 {cat_filter}
        """, params).fetchall()

        scored = []
        for r in vec_rows:
            mem_vec = _blob_to_vec(r["embedding"])
            sim = _cosine_similarity(query_vec, mem_vec)
            scored.append((r, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        for r, sim in scored[: limit * 2]:
            mid = r["id"]
            if mid in results:
                results[mid]["vec_score"] = sim
            else:
                results[mid] = {
                    "id": mid,
                    "content": r["content"],
                    "category": r["category"],
                    "source": r["source"],
                    "importance": r["importance"],
                    "created_at": r["created_at"],
                    "recalled_count": r["recalled_count"],
                    "fts_score": 0.0,
                    "vec_score": sim,
                }

    # --- 3. Combined scoring ---
    for mid, info in results.items():
        recency = _recency_score(info["created_at"])
        info["final_score"] = (
            WEIGHT_VECTOR * info["vec_score"]
            + WEIGHT_FTS * info["fts_score"]
            + WEIGHT_RECENCY * recency
        )

    MIN_SCORE = 0.35
    ranked = [r for r in results.values() if r["final_score"] >= MIN_SCORE]
    ranked.sort(key=lambda x: x["final_score"], reverse=True)
    ranked = ranked[:limit]

    for r in ranked:
        if "id" in r:
            db.execute(
                "UPDATE memories SET recalled_count = recalled_count + 1 WHERE id = ?",
                (r["id"],),
            )
    db.commit()
    db.close()

    bank_results = _search_bank(query_vec, query, limit=5)
    ranked.extend(bank_results)
    ranked.sort(key=lambda x: x["final_score"], reverse=True)

    return ranked[:limit]


def search_text(query: str, limit: int = 10) -> str:
    """Search and return formatted text"""
    results = search(query, limit)
    if not results:
        return "No matching memories found"
    lines = []
    for r in results:
        score = f"{r['final_score']:.2f}"
        created = r.get('created_at', '')
        lines.append(f"[{r['category']}|{r['source']}|{created}] (relevance:{score}) {r['content'][:200]}")
    return "\n".join(lines)


def get_all(category: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Get all memories (by time desc)"""
    db = _get_db()
    cat_filter = "WHERE category = ?" if category else ""
    params = (category,) if category else ()
    rows = db.execute(
        f"SELECT * FROM memories {cat_filter} ORDER BY created_at DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# ─── Daily Log ───────────────────────────────────────────

def daily_log(text: str) -> str:
    """Append to today's daily log"""
    today = _now_local().strftime("%Y-%m-%d")
    DAILY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DAILY_LOG_DIR / f"{today}.md"

    now_time = _now_local().strftime("%H:%M")
    entry = f"- [{now_time}] {text}\n"

    needs_header = not log_file.exists() or log_file.stat().st_size == 0
    with open(log_file, "a", encoding="utf-8") as f:
        if needs_header:
            f.write(f"# {today} Log\n\n")
        f.write(entry)

    db = _get_db()
    existing = db.execute("SELECT content FROM daily_logs WHERE date = ?", (today,)).fetchone()
    if existing:
        new_content = existing["content"] + entry
        db.execute("UPDATE daily_logs SET content = ? WHERE date = ?", (new_content, today))
    else:
        db.execute("INSERT INTO daily_logs (date, content) VALUES (?, ?)", (today, entry))
    db.commit()
    db.close()

    return f"Logged to {today}"


# ─── Notification Dedup ──────────────────────────────────

def was_notified(content_key: str, hours: int = 24) -> bool:
    """Check if already notified in the past N hours"""
    db = _get_db()
    cutoff = (_now_local() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    row = db.execute(
        "SELECT 1 FROM notifications WHERE content LIKE ? AND created_at > ? LIMIT 1",
        (f"%{content_key}%", cutoff),
    ).fetchone()
    db.close()
    return row is not None


def record_notification(content: str):
    """Record a sent notification"""
    db = _get_db()
    db.execute(
        "INSERT INTO notifications (content, created_at) VALUES (?, ?)",
        (content, _now_str()),
    )
    db.commit()
    db.close()


# ─── CC Remote Tasks ────────────────────────────────────

def submit_task(prompt: str, source: str = "chat") -> dict:
    """Submit a task for CC to execute (async)."""
    db = _get_db()
    db.execute(
        "INSERT INTO cc_tasks (prompt, status, source, created_at) VALUES (?, 'pending', ?, ?)",
        (prompt, source, _now_str()),
    )
    task_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    db.close()

    import threading
    t = threading.Thread(target=_execute_task, args=(task_id, prompt), daemon=True)
    t.start()

    return {"task_id": task_id, "status": "pending", "message": f"Task submitted (ID: {task_id}), CC is running"}


def check_task(task_id: int) -> dict:
    """Check task status and result."""
    db = _get_db()
    row = db.execute(
        "SELECT id, prompt, status, result, created_at, started_at, completed_at FROM cc_tasks WHERE id = ?",
        (task_id,),
    ).fetchone()
    db.close()
    if not row:
        return {"error": f"Task {task_id} not found"}
    return {
        "task_id": row["id"],
        "prompt": row["prompt"][:100] + ("..." if len(row["prompt"]) > 100 else ""),
        "status": row["status"], "result": row["result"],
        "created_at": row["created_at"], "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def list_tasks(limit: int = 10) -> list[dict]:
    """List recent tasks."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, prompt, status, created_at, completed_at FROM cc_tasks ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    return [{
        "task_id": r["id"],
        "prompt": r["prompt"][:80] + ("..." if len(r["prompt"]) > 80 else ""),
        "status": r["status"], "created_at": r["created_at"], "completed_at": r["completed_at"],
    } for r in rows]


def _execute_task(task_id: int, prompt: str):
    """Execute a CC task in background (subprocess)."""
    import subprocess
    import os as _os

    db = _get_db()
    db.execute("UPDATE cc_tasks SET status = 'running', started_at = ? WHERE id = ?", (_now_str(), task_id))
    db.commit()
    db.close()

    import shutil as _shutil
    claude_bin = _shutil.which("claude") or _os.path.expanduser("~/.local/bin/claude")
    env = {**_os.environ}
    env.pop("CLAUDECODE", None)
    env["PATH"] = _os.path.expanduser("~/.local/bin") + ":" + _os.path.expanduser("~/.bun/bin") + ":" + env.get("PATH", "")

    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt, "--permission-mode", "auto",
             "--output-format", "text", "--max-budget-usd", "1.00"],
            capture_output=True, text=True, timeout=300, env=env,
        )
        output = result.stdout.strip() or result.stderr.strip() or "(no output)"
        status = "completed"
    except subprocess.TimeoutExpired:
        output = "Task timed out (5 minutes)"
        status = "timeout"
    except Exception as e:
        output = f"Execution error: {str(e)}"
        status = "error"

    db = _get_db()
    db.execute(
        "UPDATE cc_tasks SET status = ?, result = ?, completed_at = ? WHERE id = ?",
        (status, output, _now_str(), task_id),
    )
    db.commit()
    db.close()

    # Write completion summary to message bus
    summary = output[:100] if len(output) <= 100 else output[:97] + "..."
    bus_post("cc_task", "out", f"[Task#{task_id} {status}] {summary}")


# ─── Message Bus (cross-channel shared context) ─────────

MESSAGE_BUS_LIMIT = int(os.environ.get("MESSAGE_BUS_LIMIT", 40))


def bus_post(source: str, direction: str, content: str) -> None:
    """Write a message to the bus. Auto-prunes old messages beyond limit.
    source: telegram/wechat/chat/cc_task/scheduled/heartbeat
    direction: in (user sent) / out (Claude sent)
    content: message content (auto-truncated to 200 chars)"""
    if len(content) > 200:
        content = content[:197] + "..."

    db = _get_db()
    db.execute(
        "INSERT INTO message_bus (source, direction, content, created_at) VALUES (?, ?, ?, ?)",
        (source, direction, content, _now_str()),
    )
    # Auto-prune: keep only the most recent N messages
    db.execute(
        "DELETE FROM message_bus WHERE id NOT IN (SELECT id FROM message_bus ORDER BY id DESC LIMIT ?)",
        (MESSAGE_BUS_LIMIT,),
    )
    db.commit()
    db.close()


def bus_read(limit: int = 20) -> list[dict]:
    """Read recent bus messages."""
    db = _get_db()
    rows = db.execute(
        "SELECT source, direction, content, created_at FROM message_bus ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    # Return in chronological order (oldest first)
    return [dict(r) for r in reversed(rows)]


def bus_format(limit: int = 20) -> str:
    """Format bus messages for context injection."""
    messages = bus_read(limit)
    if not messages:
        return "(No recent cross-channel messages)"
    lines = ["# Recent Cross-Channel Messages\n"]
    for m in messages:
        arrow = "→" if m["direction"] == "out" else "←"
        lines.append(f"[{m['created_at']}] [{m['source']}] {arrow} {m['content']}")
    return "\n".join(lines)


# ─── Bank File Index ─────────────────────────────────────

def _index_bank_files():
    """Index markdown files in bank/ directory. Skip unchanged files."""
    if not BANK_DIR.exists():
        return
    db = _get_db()
    for md_file in BANK_DIR.glob("*.md"):
        mtime = md_file.stat().st_mtime
        existing = db.execute(
            "SELECT file_mtime FROM bank_chunks WHERE file_path = ? LIMIT 1",
            (str(md_file),),
        ).fetchone()
        if existing and abs(existing["file_mtime"] - mtime) < 1:
            continue

        db.execute("DELETE FROM bank_chunks WHERE file_path = ?", (str(md_file),))

        text = md_file.read_text(encoding="utf-8")
        chunks = _split_into_chunks(text)

        for chunk in chunks:
            chunk = chunk.strip()
            if len(chunk) < 10:
                continue
            vec = _embed(chunk)
            blob = _vec_to_blob(vec) if vec else None
            db.execute(
                "INSERT INTO bank_chunks (file_path, chunk_text, embedding, file_mtime) VALUES (?, ?, ?, ?)",
                (str(md_file), chunk, blob, mtime),
            )
    db.commit()
    db.close()


def _split_into_chunks(text: str) -> list[str]:
    """Split by markdown ## headings"""
    chunks = []
    current = []
    for line in text.split("\n"):
        if line.startswith("## ") and current:
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _search_bank(query_vec: list[float], query_text: str, limit: int = 5) -> list[dict]:
    """Search bank/ file chunks"""
    _index_bank_files()
    db = _get_db()
    results = []

    if query_vec:
        rows = db.execute(
            "SELECT chunk_text, file_path, embedding FROM bank_chunks WHERE embedding IS NOT NULL"
        ).fetchall()
        for r in rows:
            vec = _blob_to_vec(r["embedding"])
            sim = _cosine_similarity(query_vec, vec)
            if sim > 0.3:
                results.append({
                    "content": r["chunk_text"],
                    "source": Path(r["file_path"]).stem,
                    "category": "bank",
                    "final_score": sim,
                })

    query_lower = query_text.lower()
    rows = db.execute("SELECT chunk_text, file_path FROM bank_chunks").fetchall()
    for r in rows:
        if query_lower in r["chunk_text"].lower():
            entry = {
                "content": r["chunk_text"],
                "source": Path(r["file_path"]).stem,
                "category": "bank",
                "final_score": 0.8,
            }
            if not any(x["content"] == entry["content"] for x in results):
                results.append(entry)

    db.close()
    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:limit]


# ─── Memory Context (for heartbeat injection) ────────────

def get_context(query: Optional[str] = None, max_chars: int = 3000) -> str:
    """Generate memory context summary."""
    if query:
        return search_text(query, limit=10)

    db = _get_db()
    rows = db.execute("""
        SELECT content, category, source, created_at, importance
        FROM memories
        ORDER BY
            CASE WHEN importance >= 7 THEN 0 ELSE 1 END,
            created_at DESC
        LIMIT 20
    """).fetchall()
    db.close()

    if not rows:
        return "(No memories yet)"

    lines = ["# Memory Summary\n"]
    total = 0
    for r in rows:
        line = f"- [{r['category']}] {r['content']}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    return "\n".join(lines)


# ─── MEMORY.md Index Rebuild ─────────────────────────────

MAX_MEMORY_MD_CHARS = 20000

def _rebuild_index():
    """Rebuild MEMORY.md — grouped by category, sorted by importance"""
    db = _get_db()
    lines = ["# Memory Index\n", f"*Last updated: {_now_str()}*\n"]

    total = db.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
    lines.append(f"*{total} memories*\n")

    categories = db.execute(
        "SELECT DISTINCT category FROM memories ORDER BY category"
    ).fetchall()

    char_count = sum(len(l) for l in lines)
    for cat_row in categories:
        cat = cat_row["category"]
        rows = db.execute(
            """SELECT content, source, created_at, importance
               FROM memories WHERE category = ?
               ORDER BY importance DESC, created_at DESC""",
            (cat,),
        ).fetchall()
        if not rows:
            continue

        section = [f"\n## {cat}"]
        for r in rows:
            line = f"- {r['content']}"
            new_chars = char_count + len("\n".join(section)) + len(line) + 2
            if new_chars > MAX_MEMORY_MD_CHARS:
                section.append(f"- ...(use memory_search for more)")
                break
            section.append(line)

        lines.extend(section)
        char_count = sum(len(l) for l in lines)
        if char_count > MAX_MEMORY_MD_CHARS:
            break

    db.close()

    with open(MEMORY_INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ─── Data Migration ──────────────────────────────────────

def migrate_from_json(json_path: Optional[str] = None):
    """Migrate from legacy memory.json to SQLite"""
    if json_path is None:
        json_path = PROJECT_DIR / "memories" / "memory.json"

    path = Path(json_path)
    if not path.exists():
        return "No legacy memory.json found"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    for category, items in data.items():
        if category == "notifications":
            for item in items:
                record_notification(item.get("content", ""))
                count += 1
        else:
            for item in items:
                result = remember(
                    content=item.get("content", ""),
                    category=category,
                    source=item.get("source", "system"),
                    importance=7 if category == "facts" else 5,
                )
                if "Remembered" in result:
                    count += 1

    backup_path = path.with_suffix(".json.bak")
    path.rename(backup_path)
    return f"Migration complete: {count} memories. Old file backed up to {backup_path}"


# ─── Init ────────────────────────────────────────────────

_db = _get_db()
_db.close()
