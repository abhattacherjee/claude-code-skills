# Claude Sessions Overview

## Recent Sessions
```dataview
TABLE date, project, git_branch, duration_minutes
FROM "claude-sessions"
WHERE type = "claude-session"
SORT date DESC
LIMIT 20
```

## Recent Insights
```dataview
TABLE date, project, tags
FROM "claude-insights"
WHERE type = "claude-insight"
SORT date DESC
LIMIT 10
```

## Active Decisions
```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-decision" AND status = "active"
SORT date DESC
```
