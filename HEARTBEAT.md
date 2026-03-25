# Heartbeat Checklist

When the heartbeat agent wakes up, check the following items in order.
If nothing to do, return HEARTBEAT_OK — don't send unnecessary notifications.

## Morning Briefing (07:00-09:00 in your timezone)
If current time is between 07:00-09:00 and no morning message sent today,
send a morning briefing via Telegram:

Example format:
```
🌅 Good morning!

📅 Today is Saturday, March 22
🌤️ Weather: Partly cloudy, 18°C

Let me know if you need anything!
```

Mark as notified after sending. Don't repeat today.

## Routine Checks
- [ ] If more than 1 hour since last heartbeat, check for active tasks in memory

## Custom Monitors
<!-- Add your own monitoring items here -->
<!-- Format: - [ ] Description | How to check | When to notify -->

## Notification Channels
- **Telegram**: Primary channel, use reply tool (configure your chat_id)
- **WeChat**: Secondary channel (if connected)
- Send to Telegram first, WeChat as backup

## Rules
- Quiet hours (23:00-07:00): no proactive messages unless urgent
- Don't send duplicate notifications (check memory first)
- Batch multiple notifications into one message, don't spam
- Morning briefing: once per day only
