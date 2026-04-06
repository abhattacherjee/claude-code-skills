# Learning Velocity

## Topics by Frequency
```dataviewjs
let pages = dv.pages('"claude-insights"')
    .where(p => p.tags);

let topics = {};
for (let p of pages) {
    let tags = p.tags || [];
    if (!Array.isArray(tags)) tags = [tags];
    for (let tag of tags) {
        if (typeof tag === 'string' && tag.startsWith("claude/topic/")) {
            let topic = tag.replace("claude/topic/", "");
            topics[topic] = (topics[topic] || 0) + 1;
        }
    }
}

dv.table(
    ["Topic", "Notes"],
    Object.entries(topics)
        .sort((a, b) => b[1] - a[1])
        .map(([topic, count]) => [topic, count])
);
```

## Recent Retrospectives
```dataview
TABLE date, project
FROM "claude-insights"
WHERE type = "claude-retro"
SORT date DESC
LIMIT 10
```

## Error Patterns (Most Common)
```dataviewjs
let pages = dv.pages('"claude-insights"')
    .where(p => p.type === "claude-error-fix");

let topics = {};
for (let p of pages) {
    let tags = p.tags || [];
    if (!Array.isArray(tags)) tags = [tags];
    for (let tag of tags) {
        if (typeof tag === 'string' && tag.startsWith("claude/topic/")) {
            let topic = tag.replace("claude/topic/", "");
            topics[topic] = (topics[topic] || 0) + 1;
        }
    }
}

dv.table(
    ["Error Topic", "Occurrences"],
    Object.entries(topics)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 15)
        .map(([topic, count]) => [topic, count])
);
```
