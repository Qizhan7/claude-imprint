---
name: morning-briefing
description: Assemble and send a morning briefing via Telegram
triggers:
  - morning briefing
  - daily briefing
  - good morning report
---

# Morning Briefing

Assemble a morning briefing and send it via Telegram. Follow these steps:

## 1. Weather
Fetch current weather from Open-Meteo (free, no API key needed):
- Use the `read_webpage` tool with this URL, replacing YOUR_LAT and YOUR_LON with the user's coordinates (e.g. from env vars IMPRINT_LAT / IMPRINT_LON or their profile):
  `https://api.open-meteo.com/v1/forecast?latitude=YOUR_LAT&longitude=YOUR_LON&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=1`
- Parse the JSON response for current temp, high/low, rain probability
- Weather codes: 0=Clear, 1=Mostly clear, 2=Cloudy, 3=Overcast, 45=Fog, 51=Drizzle, 61=Rain, 71=Snow, 80=Showers, 95=Thunderstorm

## 2. Calendar
If Google Calendar MCP is available, check today's events using `gcal_list_events`.

## 3. Pending Tasks
Use `cc_tasks` to check for any pending or running CC tasks.

## 4. Memory Check
Use `memory_search` to look for any recent reminders or upcoming deadlines.

## 5. Compose and Send
Combine all sections into a concise briefing message and send via `send_telegram`.

Format:
```
Morning Briefing

Weather
  [condition] [temp]°C
  High [max]° / Low [min]° | Rain [prob]%

Today's Schedule
  [events or "No events"]

Pending Tasks
  [tasks or "All clear"]
```
