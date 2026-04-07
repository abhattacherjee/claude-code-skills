# Open Items — All Projects

Cross-project view of all unchecked `- [ ]` items from session notes' `## Open Questions / Next Steps` sections, scoped to the last 90 days. Items older than 90 days fall off this view — use `/check-items` (unbounded) or `/vault-search` to find them.

```dataviewjs
// Single-pass: scan all sessions in the last 90 days exactly once,
// build a master list, then render each section from in-memory data.

const cutoff90 = dv.date("today").minus(dv.duration("90 days"));
const cutoff30 = dv.date("today").minus(dv.duration("30 days"));
const cutoff7  = dv.date("today").minus(dv.duration("7 days"));

const pages = dv.pages('"claude-sessions"')
    .where(p => p.type === "claude-session" && p.date && p.date >= cutoff90);

const allItems = [];
for (const p of pages) {
    const content = await dv.io.load(p.file.path);
    if (!content) continue;
    // CRLF-tolerant: \r?\n in lookahead, split on /\r?\n/
    const match = content.match(/## Open Questions[^\r\n]*\r?\n([\s\S]*?)(?=\r?\n## |\r?\n# |$)/);
    if (!match) continue;
    const lines = match[1].split(/\r?\n/);
    for (const line of lines) {
        const m = line.match(/^- \[ \] (.+?)\s*$/);
        if (m) {
            allItems.push({
                project: p.project || "unknown",
                item: m[1],
                date: p.date,
                file: p.file.link
            });
        }
    }
}

// ----- By Project -----
dv.header(2, "By Project");

if (allItems.length === 0) {
    dv.paragraph("No open items in the last 90 days.");
} else {
    const byProject = {};
    for (const i of allItems) {
        if (!byProject[i.project]) byProject[i.project] = [];
        byProject[i.project].push(i);
    }
    const projectNames = Object.keys(byProject).sort();
    for (const project of projectNames) {
        const items = byProject[project];
        dv.header(3, project + " (" + items.length + ")");
        // Render as table to preserve clickable file link
        dv.table(
            ["Item", "Source"],
            items.map(i => [i.item, i.file])
        );
    }
}

// ----- Recent (last 7 days) -----
dv.header(2, "Recent (last 7 days)");

const recent = allItems.filter(i => i.date >= cutoff7);
if (recent.length === 0) {
    dv.paragraph("No open items from sessions in the last 7 days.");
} else {
    dv.table(
        ["Project", "Item", "Source"],
        recent.map(i => [i.project, i.item, i.file])
    );
}

// ----- Items from sessions 30-90 days ago -----
dv.header(2, "Items from sessions 30-90 days ago");
dv.paragraph("These are unchecked items captured in session notes that are 30-90 days old. The same item may also appear in a more recent session — in that case it will also show in the \"Recent\" section above. Filter is by source session date, not by item-tracking duration.");

const stale = allItems
    .filter(i => i.date < cutoff30)
    .sort((a, b) => a.date - b.date);
if (stale.length === 0) {
    dv.paragraph("No items from sessions 30-90 days ago.");
} else {
    dv.table(
        ["Project", "Item", "From", "Source"],
        stale.map(i => [i.project, i.item, i.date.toFormat("yyyy-MM-dd"), i.file])
    );
}

// ----- Stats -----
dv.header(2, "Stats");

const statsByProject = {};
let oldestDate = null;
for (const i of allItems) {
    statsByProject[i.project] = (statsByProject[i.project] || 0) + 1;
    if (!oldestDate || i.date < oldestDate) oldestDate = i.date;
}

dv.paragraph("**Total open items (last 90 days):** " + allItems.length);
dv.paragraph("**Projects with open items:** " + Object.keys(statsByProject).length);
if (oldestDate) {
    dv.paragraph("**Oldest open item from:** " + oldestDate.toFormat("yyyy-MM-dd"));
}

if (Object.keys(statsByProject).length > 0) {
    dv.table(
        ["Project", "Open Items"],
        Object.entries(statsByProject).sort((a, b) => b[1] - a[1])
    );
}
```
