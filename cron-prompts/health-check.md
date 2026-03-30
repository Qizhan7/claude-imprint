# Health Check (no personality needed)

1. Use system_status tool to check system state
2. If all healthy → only output: HEALTH_OK
3. If issues found → send_telegram with description, then output:
   SENT_TG: [Health Check] <issue description>

Do not send messages unless there is an actual problem.
