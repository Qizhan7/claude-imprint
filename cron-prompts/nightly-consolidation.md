# Nightly Memory Consolidation

## Steps

### 1. Review today's memories
Use memory_search for today's date. Store any important unstored info with memory_remember.
Skip trivial items (small bug fixes, routine operations).

### 2. Deduplicate
Call memory_find_duplicates(0.85). For pairs:
- >0.92 similarity: keep the more complete one, delete the other
- 0.85-0.92: merge if same topic, skip if different

### 3. Clean stale memories
Call memory_find_stale(14). Review:
- Completed tasks → delete
- Personal info / important events → keep regardless of importance
- Uncertain → keep

### 4. Write daily summary
Use memory_daily_log: "Today: [point1], [point2], [point3]"

## Output
"Consolidation done: added X, merged/deleted Y, stale Z"
No SENT_TG needed (silent task).
