# This Week in Claude

```dataview
TABLE date, project, type
FROM "claude-sessions" OR "claude-insights"
WHERE date >= date(today) - dur(7 days)
SORT date DESC
```
