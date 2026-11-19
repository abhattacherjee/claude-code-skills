# Plan: pr-audit.py post paces writes and backs off on GitHub's secondary rate limit (#292)

Issue: #292 (folds in #300, #319, #329, #330). Base: `develop`.

## Goal

`pr-audit.py post` sends every write (new thread, reply, summary review, summary
update, thread resolve) through one paced, retrying path. The gap between writes
holds across every `pr-audit.py` process on the machine, so concurrent
`/review:deep` runs on one account do not burst. A secondary-rate-limit response
is retried after `Retry-After` (else a capped exponential back-off). When the
retry budget runs out, the run stops writing, reports what it did not attempt,
and names the rate limit as the cause. Exit codes stay as they are.

## Design

All in `plugins/review/skills/adversarial/scripts/pr-audit.py`.

- **Writes run `gh api -i`.** Real gh prints the status line and headers, a
  blank line (`\r\n\r\n`), then the body, to stdout, on success and on an HTTP
  error (gh still exits 1 on an error, with `gh: <message> (HTTP NNN)` on
  stderr). Split the header block from the body on the first
  `\r?\n\r?\n`. On success, parse the body as before. Reads (`comments()`,
  `reviews()`, `threads()`, `login()`, `repo view`) stay as they are: no `-i`,
  no pacing.
- **Rate-limit detection.** A failed write is rate-limited when any of these
  hold, case-insensitive, over stderr plus the response body: `secondary rate
  limit`, `submitted too quickly`, `abuse detection`; or the status is 429; or
  the status is 403 with `x-ratelimit-remaining: 0` (primary limit). Detection
  runs before the 422 check, so a 422 that says "submitted too quickly" is a
  rate limit, never an anchor rejection (`open_thread` must not fall back to a
  file-level comment for it). `GhError` gains `rate_limited` (bool) and
  `retry_after` (float seconds or None). `GhError.status` stays 422 only for a
  422 that is not rate-limited.
- **Wait time.** `retry-after` header (seconds) when present; else
  `x-ratelimit-reset` minus now when `x-ratelimit-remaining` is 0; else
  `PR_AUDIT_BACKOFF_BASE * 2**attempt`, capped at `PR_AUDIT_BACKOFF_CAP`.
- **Shared pacing state.** File `$PR_AUDIT_STATE_DIR/write-pace.json`
  (default `~/.cache/pr-audit`), guarded by `fcntl.flock` on
  `$PR_AUDIT_STATE_DIR/write-pace.lock`. It holds `last_write` and
  `blocked_until` (epoch floats). Before a write: take the lock, read the state,
  compute `ready = max(last_write + gap, blocked_until)`. If `ready > now`,
  release the lock, sleep `ready - now`, try again. Else run the gh call while
  still holding the lock (this serialises writes machine-wide), set
  `last_write = time.time()` after it returns, and on a rate limit set
  `blocked_until = now + wait`, so every other process waits too. A missing,
  empty or corrupt state file reads as `{}`. When the directory cannot be
  created or locked, print one stderr note and fall back to in-process pacing
  (the same gap, no sharing): pacing is advisory and must never block posting.
- **Retry budget.** At most `PR_AUDIT_RETRIES` retries per write, and at most
  `PR_AUDIT_RETRY_BUDGET` seconds of total rate-limit waiting per run. A wait
  that would overrun the budget is not slept. When either runs out, the
  `GitHub` object is marked blocked: every later write in the run raises a
  rate-limited `GhError("not attempted: GitHub's secondary rate limit")`
  without calling gh.
- **Summary.** After the counts line, when any failure was rate-limited, print
  one stderr line: `pr-audit: <k> of <n> failed posts hit GitHub's rate limit;
  rerun the same command later and it posts only what is missing`. The existing
  `FAILED ...` lines stay. Exit 1, as today.
- **Env vars** (read once per run; a bad value is a usage error, exit 2, with
  the variable named):

  | Variable | Default | Meaning |
  |---|---|---|
  | `PR_AUDIT_WRITE_GAP` | `1.0` | Minimum seconds between writes; `0` turns pacing off |
  | `PR_AUDIT_RETRIES` | `4` | Retries per write after a rate limit |
  | `PR_AUDIT_BACKOFF_BASE` | `60` | First back-off in seconds when there is no `retry-after` |
  | `PR_AUDIT_BACKOFF_CAP` | `600` | Largest single back-off |
  | `PR_AUDIT_RETRY_BUDGET` | `300` (300 after review; was 900) | Total seconds one run may spend waiting on rate limits |
  | `PR_AUDIT_STATE_DIR` | `~/.cache/pr-audit` | Where the shared pacing state lives |

The 60 s base follows GitHub's guidance: with no `retry-after`, wait at least a
minute, then back off exponentially. Retrying a rejected write is safe: GitHub
did not create the content.

Not done here: folding a round into one summary comment, and a distinct exit
code (see #292, "Not in scope here").

## Failure modes

- **Fail-open paths:** an unreadable or corrupt pace file must not skip the gap
  (test: corrupt JSON in the state file, writes still spaced); an unlockable
  state dir falls back to in-process pacing with a note (test: state dir is a
  file); a rate-limited write must never count as posted (test: retries
  exhausted → `failed`, not `posted`); a 422 "submitted too quickly" on an
  inline comment must not fall back to file-level (test).
- **Exit codes:** rate-limit failures still exit 1 (test); a bad env value exits
  2 (test); unexpected errors stay exit 3.
- **Date boundaries:** none apply: all times are epoch seconds and durations; no
  calendar dates. Checked: `retry-after` is read only as delta seconds (an
  HTTP-date value is ignored and the back-off applies; test).
- **Doc counts:** the SKILL.md and CHANGELOG entries name six env vars; the
  test counts them against the plan table.
- **Broken Markdown:** CHANGELOG lines go inside `[Unreleased]`; markdownlint in
  preflight.
- **Unrelated changes:** none planned; checked with `git diff --stat` and
  `--diff-filter=D` at self-check.
- **Inputs:** gh's stdout header block (source of truth: the real gh's `-i`
  format, checked live on 2026-11-19: headers end with `\r\n\r\n`), the pace
  state file (a missing or corrupt copy reads as `{}`; test), and the env vars.

## Bypass routes

Pacing is a throttle, not a gate. The cheapest bypass is a second machine on the
same account; out of scope and noted in the docs. Inside one machine, a process
that sets `PR_AUDIT_STATE_DIR` elsewhere opts out of sharing; that is the test
hook, documented as such.

## Task 1: paced, retrying write path

Delegate: codex — self-contained: three files in one scripts dir, one test command.

Files:
- `plugins/review/skills/adversarial/scripts/pr-audit.py`
- `plugins/review/skills/adversarial/scripts/fixtures/gh_stub.py`
- `plugins/review/skills/adversarial/scripts/test_pr_audit.py`

Stub: accepts `-i` (prints `HTTP/2.0 <code> <reason>\r\n<headers>\r\n\r\n<body>`
on stdout, on success and on error); logs `"t": time.time()` per call; new state
key `rate_limit`: a list of `{"kind": "comment|reply|review|review_update|resolve",
"times": N, "form": "secondary|too_quickly|too_quickly_422|primary",
"retry_after": <seconds or null>}` that makes the next N calls of that kind fail.

Tests (in `test_pr_audit.py`, new class `RateLimitTests`; the `Harness` sets
`PR_AUDIT_WRITE_GAP=0`, `PR_AUDIT_BACKOFF_BASE=0.05`, and a temp
`PR_AUDIT_STATE_DIR` by default, so existing tests stay fast and never touch
`~/.cache`):
- writes are spaced by at least the gap (`PR_AUDIT_WRITE_GAP=0.3`, from stub
  timestamps), reads are not paced;
- two concurrent `post` processes sharing one state dir keep every write at
  least the gap apart;
- a 403 secondary limit with `retry-after: 1` is retried after at least 1 s and
  the post succeeds;
- each form (`secondary`, `too_quickly`, `too_quickly_422`, `primary`) is
  retried;
- 422 "submitted too quickly" on an inline comment is retried inline, never
  posted file-level;
- retries exhausted: that item fails, later writes are not attempted (no gh
  call), exit 1, stderr names the rate limit and the rerun;
- `blocked_until` set by one process delays another's first write;
- corrupt state file and unlockable state dir;
- bad env value exits 2 naming the variable.

Check: `(cd plugins/review/skills/adversarial/scripts && /usr/bin/python3 -m unittest test_pr_audit test_pr_audit_recheck)`

## Task 2: docs and the sink tests

Delegate: claude — docs across two skills plus run-tests.sh env wiring; judgment on wording.

- `pr-audit.py` docstring: pacing, retry and env vars.
- `plugins/review/skills/adversarial/SKILL.md` and `plugins/review/skills/deep/SKILL.md`
  (wherever `pr-audit.py post` is described): the env var table, and that a
  rate-limit exit 1 is fixed by rerunning later.
- `CHANGELOG.md` `[Unreleased]` entries: the skill's and the plugin's.
- `run-tests.sh` sink section: export `PR_AUDIT_WRITE_GAP=0` and a temp
  `PR_AUDIT_STATE_DIR`.

Check: `bash plugins/review/skills/adversarial/scripts/run-tests.sh` and `./scripts/commit-preflight.sh`.
