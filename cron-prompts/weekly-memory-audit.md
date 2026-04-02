# Weekly Memory Audit
# Runs once a week. Verifies experience/tasks memories against actual code state.
# Does not notify the user.

## Rationale
Other CC sessions may change code without updating related memories.
This task cross-checks memories with the actual codebase to fix stale info.

## Steps

### 1. Scan recent changes
Check git logs for the past week in your project repositories:
```bash
git log --oneline --since="7 days ago"
```
Note which modules/features were changed.

### 2. Search related memories
For each changed module/feature, use memory_search with relevant keywords.
For example, if git log shows changes to compress.py → search "compress" "compression" "context".

### 3. Verify and fix
For each experience/tasks memory found, read the relevant code to confirm accuracy:
- Memory says "X feature not implemented yet" → code now has it → memory_update or memory_delete
- Memory says "using approach A" → code switched to approach B → memory_update
- Memory says "there's a bug in X" → bug is fixed → update to lesson learned or delete
- Task marked as todo → already completed → memory_delete

### 4. Record
Use memory_daily_log:
"Weekly audit: scanned X commits, reviewed Y memories, updated Z, deleted W"

## Rules
- Only touch experience and tasks category memories
- Do not touch facts (personal info) or events (milestones, emotional memories)
- When uncertain, keep the memory — better to over-retain than accidentally delete
- Do not send Telegram notifications

## Output
Print the audit summary.
