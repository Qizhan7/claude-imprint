# Customizing Your Claude

Claude Imprint uses Markdown files to define personality, behavior, and knowledge. This guide explains each file and how they work together.

## File overview

```
~/.claude/CLAUDE.md          ← The brain. You write this.
    │
    ├── references →  HEARTBEAT.md      ← Behavior rules. You write this.
    ├── references →  MEMORY.md         ← Auto-generated. Don't edit.
    └── references →  memory/bank/*.md  ← Knowledge files. You + Claude write these.
```

## `~/.claude/CLAUDE.md` — The brain

The most important file. Claude Code reads it at the start of every session. Put everything here that Claude should **always know**:

- Who you are (name, timezone, language)
- Personality and communication style
- Rules for memory, notifications, quiet hours
- Technical preferences

This file lives in `~/.claude/` so it applies across all Claude Code sessions.

### Example

```markdown
# My Assistant

## About Me
- Name: Alex
- Timezone: UTC-5 (EST)
- Languages: English

## Personality
- Casual, concise, slightly playful
- Don't over-explain things I already know

## Memory Rules
- Save important info with memory_remember
- Search memory before saying "I don't know"
- Don't store code patterns or file paths derivable from the codebase

## Notifications
- Telegram chat_id: 12345678
- Quiet hours: 23:00-07:00 — no proactive messages
- Important = notify immediately. Trivial = save for when I ask
```

A full starting template is at `examples/CLAUDE.md.example`.

### Advanced: Auto-updated sections

You can add an `AUTO` section at the bottom of CLAUDE.md that gets updated by scripts (e.g., the post-response hook syncs recent cross-channel messages here). Mark it clearly so you know not to hand-edit it:

```markdown
## AUTO — auto-generated (do not edit below this line)
[recent messages will appear here]
```

## `HEARTBEAT.md` — Heartbeat behavior

Defines what the heartbeat agent checks each time it wakes up:

- Morning greeting / briefing
- Routine monitors (calendar, tasks, health reminders)
- When and how to send notifications
- Quiet hours behavior

Edit this to match your schedule and preferences.

## `memory/bank/*.md` — Knowledge files

Long-form structured knowledge that gets indexed for semantic search. Common files:

- **`preferences.md`** — Your habits, dietary needs, daily routines
- **`experience.md`** — Technical lessons, debugging insights
- **`relationships.md`** — People you mention, their roles

You can edit these directly, or just tell Claude — *"remember that I'm lactose intolerant"* — and it will write to the right file.

Add any `.md` file here; it's automatically included in search.

## `MEMORY.md` — Memory index (auto-generated)

Rebuilt on every memory write. Gives Claude a quick snapshot of stored memories without querying the database. Don't edit — it gets overwritten.

## `memory/YYYY-MM-DD.md` — Daily logs (auto-generated)

One file per day, append-only. Created by `memory_daily_log` and the pre-compaction hook. No need to edit.

## Getting started

1. Copy `examples/CLAUDE.md.example` → `~/.claude/CLAUDE.md`, fill in your info
2. Edit `HEARTBEAT.md` to set your notification preferences
3. Optionally add files to `memory/bank/` for structured knowledge
4. MEMORY.md and daily logs will populate automatically
