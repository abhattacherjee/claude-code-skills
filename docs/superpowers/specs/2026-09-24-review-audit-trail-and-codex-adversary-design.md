# Review audit trail on the PR, and Codex as adversary — design

Issue: #135. Skills: `adversarial-review`, `deep-review`.

## Goal

Two changes to the two review skills:

1. **Audit trail.** When a review runs against a PR, every exchange between the models is saved on
   the PR, round by round, so the conversation and its iterations can be audited later.
2. **Codex adversary.** When the Codex CLI is installed and logged in, it replaces Gemini as the
   opposing model. The order is Codex, then Gemini, then Claude-only.

The audit trail is built first. It does not depend on which model is the adversary, and it replaces
the current PR posting path, which is broken (see "Current state").

## Decisions made during design

| Question | Decision |
|---|---|
| What is recorded | The structured exchange: findings, verdicts with reasons, counters, fixes or pushback, re-checks, and the SHA each applied to. Not raw prompts or raw model output. |
| Layout on the PR | One inline thread per finding. Later events are replies in that thread. One summary review per round. |
| Refuted findings | Get an inline thread too, with the refutation as a reply, and the thread is resolved straight away. |
| When it posts | On by default whenever the run targets a PR. `--no-post` turns it off. With no PR, the same content goes to the local report file. |
| Where the logic lives | One script, `pr-audit.py`, in `adversarial-review`. `deep-review` calls it. |
| Issue scope | One issue, #135, for both parts. |

## Current state (verified 2026-09-24)

- `adversarial-review` PR mode never posts. `sink.sh:273` calls
  `pr-review-cli.sh --pr N --body …`, but that CLI takes subcommands and exits with
  `unknown subcommand '--pr'`. Each finding counts as failed on stderr, then `sink.sh:291` prints
  "PR review comments posted" anyway.
- Only findings both models confirm (`status == "survivor"`) are ever sent to PR delivery. Refuted
  and unconfirmed findings are dropped from the PR.
- `deep-review` posts nothing to the PR and keeps no per-round record.
- Nothing handles GitHub's 65,536-character comment limit, and nothing redacts secrets.
- The run directory (`mktemp -d`) holds `r1-*.json`, `r2-*-verdicts.json`, `report.md` and
  `report.json`, and is never deleted. Raw Gemini output is deleted by `gemini-review.sh`'s EXIT
  trap.
- `deep-review/SKILL.md` says `gemini-review.sh` has no `--mode find`, and tells the reader to call
  `gemini` directly for R1. That is stale: `gemini-review.sh` supports `--mode find|judge`.

## Part 1 — Audit trail

### The round record

After each round, the calling skill writes `round-<k>.json` to its run directory. It extends the
existing findings shape with `events`, the ordered exchange for that round.

```json
{
  "schema": "audit-round/v1",
  "run_id": "ar-20260924-1a2b",
  "skill": "deep-review",
  "phase": "phase2",
  "round": 2,
  "adversary": "codex",
  "head_sha": "<40 hex chars>",
  "prev_head_sha": "<40 hex chars or null>",
  "findings": [
    {
      "id": "X-003",
      "origin": "codex",
      "path": "src/a.py",
      "line": 41,
      "severity": "important",
      "category": "bug",
      "title": "Retry loop never resets the backoff",
      "rationale": "…",
      "status": "survivor",
      "events": [
        {"by": "claude", "kind": "verdict", "verdict": "confirm", "text": "…"},
        {"by": "claude", "kind": "resolution", "resolution": "fixed", "sha": "<40 hex>", "text": "…"}
      ]
    }
  ]
}
```

- `run_id` is set once per skill invocation. It groups the rounds of one run.
- `status` is `survivor`, `rejected` or `unconfirmed`, as today.
- `events[].by` is `claude`, `codex` or `gemini`. `events[].kind` is one of:
  - `verdict`, with `verdict: confirm|refute`
  - `counter`
  - `resolution`, with `resolution: fixed|pushback|deferred`, and `sha` when the fix is committed.
    `sha` is optional because deep-review Phase 1 commits only at the end of the phase. A `fixed`
    event without `sha` renders as "fixed (not yet committed)".
  - `recheck`, with `result: resolved|partly|missed`
- A finding can appear in several rounds. Only that round's new events go in each record.
- Finding ids match `^[A-Z][A-Z0-9]{0,3}-\d{3,}$` and are unique within a run. deep-review Phase 1
  uses `R-001…`; Phase 2 keeps `C-`, `G-` and, with Codex, `X-`.

### `scripts/pr-audit.py`

It lives in `plugins/adversarial-review/skills/adversarial-review/scripts/` and has two modes:

- `pr-audit.py post --pr N [--repo owner/name] --record round.json`
- `pr-audit.py local --record round.json --out <file>`
- `pr-audit.py record --report-json report.json …` builds a round record from adversarial-review's
  `report.json`, so that skill never hand-writes the JSON.

`post` does the following, in order:

1. Validate the record against `audit-round/v1`. Exit 2 on a malformed record or a `head_sha` that
   is not 40 hex characters.
2. Check that `gh` exists and is logged in. If not, fall back to `local` and print why.
3. Fetch the PR's review comments once (paginated). Build a map from marker to comment id.
4. For each finding:
   - **No thread yet:** post it as its own review comment
     (`POST /repos/{o}/{r}/pulls/{N}/comments`, with `commit_id: head_sha`). Posting each thread
     separately means one line GitHub rejects cannot sink the others.
   - **Thread exists:** post each new event as a reply
     (`POST /repos/{o}/{r}/pulls/{N}/comments/{id}/replies`).
   - Skip any comment whose marker is already on the PR. This makes re-running safe.
5. Post the round's summary as a review (`POST /repos/{o}/{r}/pulls/{N}/reviews`,
   `event: COMMENT`, `commit_id: head_sha`), after the threads, so its table can link to them.
6. Resolve threads with GraphQL `resolveReviewThread`, following the rules below.
7. Print the posted, skipped and failed counts. Exit 0 if nothing failed. Exit 1 on any failure,
   listing each failed id with the `gh` error text.

`local` renders the same content as markdown and appends it to the report file, which is today's
gitignored `<branch>.adversarial-review.md`.

### Markers

Every comment ends with a hidden marker:

`<!-- audit:v1 run=<run_id> finding=<id> event=<round>.<index> -->`

The first comment of a thread uses `event=<round>.0`. The script finds prior threads by searching
for `run=<run_id> finding=<id>`. It keeps no local state, so a second session or a re-run continues
the same threads.

### Comment format

Thread opener, posted at `path:line`:

```
**[Codex] [important] bug** — Retry loop never resets the backoff

<rationale>

Round 1 · phase2 · reviewed at `a1b2c3d`
<!-- audit:v1 run=… finding=X-003 event=1.0 -->
```

Replies are tagged with the model that made the event:

- `[Claude] verdict: refute — <reason>`
- `[Codex] counter — <argument>`
- `[Claude] fixed in e4f5a6b — <what changed>`
- `[Claude] pushback — <evidence>`
- `[Codex] re-check: resolved | partly | missed — <reason>`

### Thread resolution

| Finding | Thread |
|---|---|
| Refuted (`status: rejected`) | Refutation posted as a reply, then resolved at once. |
| Fixed | Stays open until a later round records `recheck: resolved` from the adversary. Then resolved. |
| Pushback | Stays open. A person settles it. |
| Unconfirmed | Stays open. |

The adversary confirms a fix, not the author.

### Round summary

One `COMMENT` review per round, never `APPROVE` or `REQUEST_CHANGES`. Its body:

```
**deep-review · Phase 2 · Round 2** · adversary: Codex · reviewed `e4f5a6b` (previous `a1b2c3d`)
5 findings: 2 new · 1 fixed, re-checked resolved · 1 refuted · 1 pushback open

| id | severity | origin | this round | thread |
|---|---|---|---|---|
| X-003 | important | codex | fixed → resolved | [link] |

Redacted: 0 · Posting failures: 0
<!-- audit:v1 run=… summary round=2 -->
```

### When an inline comment is not possible

- If the line is not in the PR diff, GitHub rejects the comment with 422. Retry it as a file-level
  comment (`subject_type: file`). If that also fails, list the finding in the summary table with no
  thread, marked `no thread: <reason>`.
- A finding with no `path` goes in the summary only.

### Secrets

Every outgoing body is scanned before posting for:

- GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`)
- AWS access key ids (`AKIA…`, `ASIA…`)
- OpenAI and Anthropic keys (`sk-…`, `sk-ant-…`)
- private key blocks (`-----BEGIN … PRIVATE KEY-----`)
- JWTs (three base64url segments starting `eyJ`)

A match is replaced with `[REDACTED:<type>]` and counted in the summary. The list is deliberately
narrow. It stops a model quoting a secret from the diff. It is not general data-loss prevention.

### Size limits

- A comment body over 60,000 characters is cut at a line boundary and ends with
  `… truncated (N chars); full record in the run dir`.
- A summary table that would pass the limit is split into `Round 2 (1/2)`, `(2/2)`.

### Changes to the callers

**adversarial-review**

- `sink.sh`: replace `deliver_pr` with a call to `pr-audit.py post`. Delete the `pr-review-cli.sh`
  lookup (`sink.sh:133-163`). Print the script's counts, and never print a success line when
  anything failed. A new exit code 4 means the report was delivered but the audit trail is
  incomplete.
- `SKILL.md`: after synthesis, write `round-1.json` from the R1 findings and R2 verdicts, including
  refuted findings. Add `--no-post`.

**deep-review**

- `SKILL.md`: generate `run_id` in Phase 0. After every Phase 1 and Phase 2 round, write
  `round-<k>.json` and call `pr-audit.py` (`post` in PR mode, `local` otherwise, nothing with
  `--no-post`). Rounds are numbered across both phases, and `phase` tells them apart.
- Re-review rounds record `recheck` events for findings fixed in the round before, so their threads
  can be resolved.
- Fix the stale `gemini-review.sh --mode find` claim, and use the script for R1.
- The final report gives the run directory path and the posted and failed counts.

A posting failure never fails the review. The skill reports it and carries on.

## Part 2 — Codex as adversary

From #135, verified on codex 0.155.1.

### Detection

- New `ensure-codex.sh --check` exports `CODEX_INSTALLED`, `CODEX_VERSION` and `CODEX_AUTHED`.
- Auth: `codex login status` exits 0 when logged in and 1 when not. It prints to stderr, so use the
  exit code, not stdout.
- Adversary order: Codex (installed and authed), then Gemini, then Claude-only.
  `--adversary codex|gemini` forces one. A forced adversary that is not usable is an error, not a
  silent fallback.
- The chosen adversary is recorded in each round record's `adversary` field.

### `codex-review.sh --mode find|judge`

Mirrors `gemini-review.sh`. It emits the same `{"findings":[...]}` and verdict shapes with
`origin: "codex"` and ids `X-001`. Invocation:

```
env -i PATH="$PATH" HOME="$HOME" CODEX_HOME=<dedicated home> \
  codex exec --ephemeral --ignore-user-config --ignore-rules \
  --disable apps --disable plugins --disable remote_plugin --disable memories \
  --disable multi_agent --disable image_generation --disable view_image \
  -s read-only -C <repo> -c model_reasoning_effort="high" \
  --output-schema <schema.json> -o <out.json> "<prompt>" </dev/null
```

- `-p` is `--profile`, not a prompt flag. The prompt is the last argument.
- Stdin must be closed, or the run hangs on "Reading additional input from stdin".
- `codex exec review --base` takes no output schema, so use plain `exec`.
- macOS has no `timeout` binary. Enforce the timeout in the script by killing the process group.
- Exit 3 means the adversary is unavailable, matching `gemini-review.sh`.

### Security

- `--disable apps` removes about 338 ChatGPT connector tools (Gmail send, GitHub merge, and so on)
  that run outside the sandbox.
- `-s read-only` still lets Codex read the whole disk: a canary file outside the repo was read.
  Review needs the shell tool to read the repo, so this trade-off stays and is documented in
  SKILL.md.
- A dedicated `CODEX_HOME` (mode 0700, no `config.toml`, no `hooks.json`) keeps the user's hooks and
  config out of the run.
- Codex output is untrusted. Validate it against the schema, cap list lengths, and pass it through
  the same redaction as Part 1 before it reaches the PR.
- Codex cannot run pytest in the read-only sandbox, because temp-file writes fail. Its claims that
  tests pass cover pure tests only.

### Re-review rounds in deep-review

Build the round-N prompt from the earlier findings plus the author's replies. For each earlier
finding, ask whether it is resolved, and record the answer as a `recheck` event. Ask for new
defects in the fix range only (`git diff <prev_head_sha>..<head_sha>`).

## Testing

A stub `gh` on `PATH` records each call and returns canned responses, in the style of the existing
`run-tests.sh`. A stub `codex` does the same for Part 2.

`pr-audit.py`:

1. First round: one review with inline comments, markers present, and `commit_id` equal to
   `head_sha`.
2. Second round: an existing marker leads to replies, not new threads.
3. A refuted finding gets a reply and its thread is resolved in the same run.
4. A fixed finding's thread stays open until a later `recheck: resolved`.
5. A 422 on an inline comment falls back to a file-level comment, then to the summary only.
6. Re-running the same record posts nothing.
7. A partial failure exits 1 and lists the failed ids, and no success line is printed.
8. A record containing a fake GitHub token posts a body without it.
9. An oversize body is truncated, and an oversize summary is split.
10. `local` mode writes markdown with the same content as the PR.
11. `--no-post` makes no `gh` calls.
12. A malformed record, or a short `head_sha`, exits 2 and posts nothing.

`codex-review.sh`: logged out (exit 1 from `codex login status`), timeout, invalid JSON, and
schema-valid output. Adversary order: Codex usable, Codex not authed so Gemini is used, neither so
Claude-only, and a forced adversary that is unusable.

Each test gets a negative control: break the guard it covers and check the test goes red.

## Done when

- `adversarial-review` PR mode posts the trail, and a failure is reported as a failure.
- `deep-review` posts every round of both phases to the PR.
- Both skills pick Codex automatically when it is usable, and fall back cleanly otherwise.
- All tests above pass, and each negative control goes red.
- One real PR has gone through `deep-review` end to end with Codex as the adversary, and its thread
  history shows each round.

## Out of scope

- Raw prompts and raw model output on the PR.
- Redacting the diff sent to Codex or Gemini.
- Deleting the run directory.
- Changing how findings are judged or the survivor rule.
