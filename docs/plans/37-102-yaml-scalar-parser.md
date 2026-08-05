# YAML scalar parser for `extract_field` (#37, #102)

Branch: `feature/37-102-yaml-scalar-parser`

The plugin README generator reads `description:` out of `SKILL.md` as raw text
instead of parsing it as a YAML scalar. Three distinct defects live in the same
six lines. Closing them one at a time leaves the class open — #37 (folded) was
filed, #102 (double-quoted) is its sibling, and a third is still unfiled — so
this replaces the reader with one parser that covers every scalar style.

## The defective code

`scripts/_lib.sh:19-24`:

```bash
extract_field() {
  local skill_md="$1"
  local field="$2"
  sed -n '/^---$/,/^---$/p' "$skill_md" | grep "^${field}:" | head -1 | \
    sed "s/^${field}:[[:space:]]*//; s/^[\"']//; s/[\"']$//"
}
```

`grep … | head -1` reads exactly one line and the trailing `sed` does two
unconditional single-character strips. That yields three defects:

### Defect 1 — folded/literal block scalars leak the indicator (#37)

`description: >-` has no text on its own line; the text is on the indented
continuation lines the reader never looks at. `extract_field` returns the
literal string `>-`. `prepare-plugin.sh` then writes that into the generated
README in two places — the `## What It Does` paragraph (line 522/527) and the
`### Skills` list entry (line 463/466). In Markdown `>-` also renders as an
empty blockquote, so the failure is silent rather than obviously broken.

### Defect 2 — double-quoted scalars leak their `\"` escapes (#102)

`s/^["']//; s/["']$//` removes only the outer quote pair. Every internal `\"`
survives verbatim into the README. Same two interpolation sites.

### Defect 3 (unfiled) — the quote strip eats legitimate characters

The two `sed` strips are unconditional and independent: they fire on the first
character and the last character regardless of whether the value is actually a
quoted scalar, and regardless of whether the two agree.

- `description: "quoted" is a word` — a plain scalar that merely *starts* with a
  quote — loses its leading `"`, yielding `quoted" is a word`.
- A plain scalar ending in an apostrophe loses it.
- A single-quoted scalar's YAML `''` escape is never collapsed to `'`.

No issue is filed for this. It is fixed here because it is the same line.

### Defect 4 (adjacent) — `short_desc` uses `echo`

```bash
short_desc() { echo "$1" | sed 's/\. Use when:.*/\./'; }
```

`echo "$1"` swallows a value beginning with `-n`/`-e`/`-E` as an option under
bash's builtin. Reachable the moment a description legitimately starts with one.
Fixed to `printf '%s\n'`.

## Measured blast radius

Call sites of the shared `_lib.sh` `extract_field` (measured, not estimated):
**12 calls across 5 scripts** — 10 extract `description`, 2 extract `name`.

| Script | Lines | Fields |
|---|---|---|
| `prepare-plugin.sh` | 420, 462, 481, 502 | description ×4 (the README generator; 481/502 read command/agent `.md` files) |
| `sync-monorepo.sh` | 579, 580, 1614 | name, description ×2 |
| `sync-individual-repos.sh` | 219, 220 | name, description |
| `prepare-skill-repo.sh` | 69, 70 | name, description |
| `release-monorepo.sh` | 156 | description |

`validate-skill.sh:96` defines its **own** single-argument `extract_field` and
is not a caller of this one. It already folds block scalars (so it does not
have defect 1) but does no unescaping (so it does have defect 2). It is a
*reference* for the folding logic only; it is not modified in this pass and is
not made to share code with `_lib.sh` — the signatures differ and merging them
is a separate change.

`short_desc` has 5 call sites, plus two places that inline the same
`sed 's/\. Use when:.*//'` rather than calling it (`sync-monorepo.sh:1614`,
`release-monorepo.sh:156`). That duplication is left alone in this pass.

Content exposure across the monorepo (all `*/SKILL.md` and
`plugins/*/skills/*/SKILL.md`, 44 files):

- **Folded (`>-`/`>`) descriptions in the repo: 0.** #37 has no live instance
  here. It is not hypothetical, though: four skills in the live authoring home
  use folded scalars and would leak on the sync that first publishes them —
  `sentry-dashboard-builder` (`>`), `sentry-deploy-notifications` (`>-`),
  `vercel-cli-agent-auth` (`>-`), `vercel-rewrite-platform-routes` (`>`).
- **Double-quoted descriptions: 40.** Of those, exactly **2 carry internal `\"`**
  and leak today: `deep-review/SKILL.md` and
  `plugins/deep-review/skills/deep-review/SKILL.md` (same text, 6 escaped pairs
  each). The other 38 are escape-free, which is why the defect is invisible
  across the catalogue.
- The remaining 4 are plain scalars.

`plugins/deep-review/README.md` is hand-curated and was never regenerated, which
is why the leak is not visible in git.

**Correction (review, 2026-08-05).** An earlier version of this paragraph said a
full `sync-monorepo.sh` run would `rsync -a --delete` over
`plugins/deep-review/` and so regress that README. **That is false.** Both plugin
write paths copy an existing destination README aside, rsync, and restore it —
`sync-monorepo.sh:1053-1068` (plugin auto-build) and `:1177-1193`
(`--add-plugin`) — unconditionally, for every plugin. No plugin README was ever
at risk from a routine sync; the leak was live only for a README that does not
yet exist at the destination, or one deleted first.

That blanket preserve has a side effect worth stating explicitly: **no plugin
README is ever refreshed by a generator improvement.** Every already-published
`plugins/*/README.md` is frozen until someone deletes or hand-edits it, so
fixing this parser does not propagate to any of them on its own.

Measured before/after over all 44 repo descriptions: **42 identical, 2 changed**
— and the 2 are exactly the deep-review pair. Plain-scalar output is unchanged.

## Design

Replace the `sed | grep | head | sed` pipeline with a single `awk` program.

**No new runtime dependency.** `awk` is already used throughout these scripts
(`extract_section`, `extract_headings`, `validate-skill.sh`). `python3` is
deliberately not introduced: these scripts run in CI and on user machines where
the current dependency set is `bash`/`sed`/`awk`/`jq`/`rsync`, and a YAML
library would be a fourth interpreter for one field.

Algorithm:

1. Collect the frontmatter — lines between the first `---` and the second —
   into an array, so continuation lines can be looked ahead to. (Same framing
   as `validate-skill.sh:92-94`.)
2. Find the first line matching `^<field>:`; strip the key and any surrounding
   horizontal whitespace.
3. If the remaining value is a **block-scalar indicator**
   (`/^[|>]([0-9][+-]?|[+-][0-9]?)?[ \t]*(#.*)?$/` — the two-branch alternation
   is deliberate: YAML permits chomping *before* indentation, so `>-2` and `>2-`
   are both legal and the simpler `[0-9]*[+-]?` accepted only the latter),
   consume the following indented lines, stopping at the first non-indented line
   (per YAML) and skipping blanks. Join with `" "` — for `|` as well as `>`.
   Folding a literal block is not what YAML specifies, but **single-line output
   is a hard contract here**: `sync-monorepo.sh:604` splices this value into a
   Markdown table row, so a newline breaks the table at exit `0`.
   `validate-skill.sh:121-131` folds both indicators identically too, and its
   header regex carries the same alternation (ported in review — the two had
   diverged inside this very change, so a file could pass CI validation and
   still publish corrupt). Two behaviours added in review: a value that begins
   with `|`/`>` but matches **no** legal header (`>10`, `>--`) now writes a
   diagnostic to stderr and **exits 3** rather than falling through to the plain
   path and returning the indicator as the description — that fall-through is
   issue #37 and it had survived two fixes; and folding a multi-line **literal**
   `|` block emits a stderr note naming the file and field, because the fold can
   change meaning and used to do so in silence.
4. Otherwise, strip quotes **only when the value genuinely opens and closes with
   the same quote character**, then unescape the contents for that style:
   - `"…"` → `\n`/`\t`/`\r` become a **space** (same single-line contract as
     above). The decoded whitespace is written as an internal marker byte so the
     collapse acts on **exactly** what the decode introduced: runs of the marker
     (with any whitespace touching them) become one space and vanish at either
     end, and a region no escape reached is returned byte-for-byte. The first
     implementation used a `sawws` flag and collapsed the whole string, which
     made the rewrite non-local — measured, `"Cost:  100  USD.\tNote."` had its
     *beginning* reformatted by a `\t` at its *end*. Every other `\<c>` becomes a
     literal `<c>`, which covers `\"`, `\\` and `\/`.
   - `'…'` → `''` collapses to `'`.
   - anything else → returned verbatim, quotes and all.
5. Emit through a single `emit()` point with `printf "%s\n", …`, never
   `print`-into-a-format, so a `%` in a description cannot be read as a
   conversion. `emit()` also replaces any literal CR/VT/FF byte with a space:
   none of the three is a YAML escape, so they otherwise travel into the value
   untouched and land inside a Markdown table cell.

Deliberate non-goals, so the diff stays reviewable:

- **Trailing `#` comments on plain scalars are not stripped.** YAML would treat
  ` # …` as a comment; the old reader kept it and so does this one. Changing it
  is unrelated scope with its own blast radius.
- **Flow collections, anchors, aliases, and multi-document files are not
  handled.** No `SKILL.md` uses them for `description`.
- A value that both starts and ends with `"` but is not actually a quoted
  scalar (`"a" or "b"`) is treated as quoted, and is stripped to `a" or "b`.
  The same-quote-at-both-ends rule therefore **narrows** the ambiguity rather
  than resolving it: it closes the far commoner `"quoted" is a word` shape and
  leaves this one. Distinguishing them needs a real YAML parse of the line.

`awk` portability: the program uses only POSIX features (`substr`, `sub`,
`length`, user functions with local parameters, ERE with `?` and groups, and
`\047`/`\042` octal escapes for the quote characters so no literal `'` has to
appear inside the shell-single-quoted program body). It runs on macOS BSD awk
and on gawk.

## Task list

- [x] **A** — this plan file.
- [x] **B** — rewrite `extract_field` in `_lib.sh`; fix `short_desc` to use
  `printf`. Applied identically to **both** copies:
  - `~/.claude/skills/skill-publishing/scripts/_lib.sh` (live authoring copy)
  - `plugins/skill-publishing/skills/skill-publishing/scripts/_lib.sh` (in-repo)

  They are byte-identical today and `test-sync-hygiene.sh` asserts it — the
  assertion described as *"live authoring copy is byte-identical to the in-repo
  copy (whole skill tree)"* — so a one-sided edit turns that assertion red.
  (Cited by description, not by line number. The plan originally cited
  `test-sync-hygiene.sh:4284`, which was already wrong — the assertion was at
  4287 on `develop`. This change's own inserted fixtures then moved it to 4496,
  and the review pass moved it again to 4940. A line number in a plan that
  edits the file it cites has a short half-life.)
- [x] **C** — regression fixtures in `scripts/test-sync-hygiene.sh` driving the
  real `prepare-plugin.sh` through its `run_prepare` helper.
- [x] **D** — prove fail-first: run the suite with the OLD parser restored and
  record which new assertions go red. Extended in review to **three** mutation
  arms, since the old parser alone leaves the descriptionless-fallback guards
  and the run-level `…fixture builds` checks untouched: old parser (33 red),
  empty-returning stub (53 red), awk compile error (65 red).

Out of scope this pass, handled separately: version bumps, CHANGELOG entries,
plugin re-assembly, marketplace/README regeneration, and the decision on whether
`plugins/deep-review/README.md` stays curated or is regenerated.

## Verification plan

**Every scalar style is asserted in both directions.** A negative-only assertion
(`assert_not_contains ">-"`) passes identically against a working parser and one
that returns the empty string, so each style gets:

- a **positive control** — `assert_contains` on a distinctive ALL-CAPS marker
  that can only appear if the scalar was parsed correctly; and
- a **negative** — `assert_not_contains` on the leaked syntax (`>-`, `\"`).

Fixtures, one plugin per scalar style, built by the real `prepare-plugin.sh`:

| Fixture | Scalar style | Positive control | Negative |
|---|---|---|---|
| `foldedscalar-plugin` | `>-` folded | folded marker text, joined with spaces | no `>-` in README |
| `dquotescalar-plugin` | `"…\"…\""` | marker with real `"` quotes | no `\"` in README |
| `squotescalar-plugin` | `'…''…'` | marker with a real `'` | no doubled `''` |
| `plainscalar-plugin` | plain, quote-adjacent | leading `"` preserved | not stripped to a bare word |

Assertions are made on the generated `README.md` in both interpolation sites —
`## What It Does` (from `FULL_DESC`) and the `### Skills` list (from `SDESC`) —
because they are separate reads and a partial fix could close one.

One further assertion covers the `!= "."` guards at `prepare-plugin.sh:464` and
`:504`: if the parser returned empty, `SDESC_SHORT` would be blank, the guard
would take its else branch, and the skills list would silently degrade to a bare
`` - `name` `` with no description at all. Nothing in the suite catches that
today, so the skills-list row is asserted whole, em-dash included.

Fail-first is mandatory and reported verbatim: restore the old
`extract_field`, run `./scripts/test-sync-hygiene.sh`, and record the FAIL
lines. Any new assertion that passes against the old parser is vacuous and is
rewritten before the work is reported complete.

One arm is not enough, and the matrix below is what was actually run. Both
copies of `_lib.sh` are mutated together, so the authoring-parity assertion does
not contribute a spurious red. Counts are FAIL lines over the whole 434-assertion
suite:

| Arm | Red |
|---|---|
| develop's `extract_field` restored | 44 |
| empty-returning `extract_field` stub | 70 |
| awk compile error inside `extract_field` | 214 |
| block-scalar terminator deleted | 5 |
| block-header regex narrowed to `/^>-$/` | 14 |
| trailing-whitespace trim deleted | 3 |
| literal-scalar newline join restored | 2 |
| pre-fix block-header regex restored | 3 |
| `\n` decoded to `"XX"` | 2 |
| fail-closed header guard reverted | 3 |
| marker-based collapse reverted to the `sawws` flag | 3 |
| literal-fold stderr note deleted | 2 |
| control-byte scrub deleted from `emit()` | 3 |

The double-space fixture with **no** escape present is a deliberate control that
stays green under the `sawws` arm — that is the whole reason it is paired with
an escape-bearing twin rather than standing alone. Reporting it as evidence for
the locality fix on its own would be the vacuous-assertion mistake this section
exists to prevent.
