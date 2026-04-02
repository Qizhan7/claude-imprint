# Nightly Memory Consolidation
# Runs silently — no notifications to the user.

## Steps

### 1. Review today's log (catch missed info)
Use memory_search for today's date. If you find important info that wasn't saved to memory yet, store it with memory_remember.
Skip: small bug fixes, routine chats, already-stored info.

### 2. Deduplicate
Call memory_find_duplicates(0.85). For similar pairs:
- Similarity > 0.92: keep the more complete one, delete the other with memory_delete
- 0.85-0.92: merge if genuinely the same thing; skip if different topics

### 3. Memory decay
Call memory_decay(days=30, dry_run=False). This automatically decrements importance by 1 for memories not recalled in 30+ days.
Memories that reach importance=0 are archived (hidden from search). Review the results — if anything important was archived by mistake, restore it with memory_update.

### 4. Stale cleanup
Call memory_find_stale(14). Review each result:
- Completed tasks → delete
- Personal info / important events → keep regardless of importance
- Uncertain → keep

### 5. Daily summary
Use memory_daily_log to write a brief summary:
"Today: [point 1], [point 2], [point 3]"
Keep it concise, 3-5 bullet points. If nothing notable happened, write "Quiet day."

## Output
"Consolidation done: added X, merged/deleted Y, stale Z"
No SENT_TG needed (silent task).
