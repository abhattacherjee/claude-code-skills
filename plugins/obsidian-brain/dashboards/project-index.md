# Project Index

## Sessions by Project
```dataview
TABLE length(rows) AS "Sessions", min(rows.date) AS "First", max(rows.date) AS "Last"
FROM "claude-sessions"
WHERE type = "claude-session"
GROUP BY project
SORT length(rows) DESC
```

## Error Fixes (troubleshooting library)
```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-error-fix"
SORT date DESC
```
