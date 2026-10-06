# Catalogue Tool and Docs Drift Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and check the plugin catalogue (root README table, `marketplace.json`, plugin README meta lines) from each `plugin.json`, guard all current docs against drift in CI and `commit-preflight.sh`, and let `skill-kit:publish` sync a plugin-only monorepo.

**Architecture:** One Python tool, `catalogue.py`, owns every catalogue write and its `--check`. A repo-only `check-doc-refs.py` checks links, paths and `plugin:skill` names. `sync-monorepo.sh` calls `catalogue.py` in every layout and gains a plugin-only mode in place of the #167 refusal.

**Tech Stack:** Python 3.9+ standard library, bash 3.2-compatible shell, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-05-catalogue-drift-guard-design.md`

## Global Constraints

- Python: standard library only; must run on python3.9 (macOS system python) and the CI ubuntu python.
- Shell: bash 3.2 compatible (no `mapfile`, no `${x,,}`, no associative arrays) in `plugins/skill-kit/skills/publish/scripts/*.sh`.
- Markers, verbatim: `<!-- catalogue:start -->`, `<!-- catalogue:end -->`, `<!-- plugin-meta:start -->`, `<!-- plugin-meta:end -->`.
- Exit codes for both checkers: 0 clean, 1 drift or broken reference, 2 cannot run (fail closed).
- Standalone plugins (no catalogue row): `git-flow`, `obsidian-brain`, read from one file, `plugins/skill-kit/skills/publish/scripts/standalone-plugins.txt`.
- Marketplace name in this repo: `claude-code-skills`. Entry key order: `name`, `source`, `description`, `version`. Other top-level keys are kept as they are.
- Tests never touch the network or the live repo; every test runs in a `mktemp -d` fixture.
- Every commit: `./scripts/commit-preflight.sh` (as its own command), stage by name, check `git diff --cached --name-only`, trailer `Co-Authored-By: <the model you are> <noreply@anthropic.com>`.
- Run suites in the foreground. A long run reports partial results about every 20 minutes.
- Plain English in docs, comments and CHANGELOGs (see `~/.claude/CLAUDE.md`).

## Review Focus

1. A description containing `|` or a newline would break the README table: `catalogue.py` must exit 2 naming the plugin (test in Task 1).
2. Non-ASCII descriptions (em dashes, arrows) must round-trip byte-identical through `marketplace.json` (`ensure_ascii=False`) (test in Task 1).
3. A README with CRLF line endings, or text after the end marker, must keep every byte outside the markers (test in Task 1).
4. A stray directory under `plugins/` with no `.claude-plugin/plugin.json` must exit 2 naming it, never be skipped silently (test in Task 1).
5. A path in a fenced code block, or with `<name>` placeholders, must not be reported; a real broken one in prose must be (tests in Task 2).

---

### Task 1: `catalogue.py` — write and check the catalogue

**Files:**
- Create: `plugins/skill-kit/skills/publish/scripts/catalogue.py`
- Create: `plugins/skill-kit/skills/publish/scripts/standalone-plugins.txt`
- Create: `scripts/test-catalogue.sh`

**Interfaces:**
- Produces: CLI `catalogue.py [--check] [--json] [--marketplace-name NAME] [--owner OWNER] <repo>`.
  - Write mode prints `WROTE <relative path>` per file it changed and exits 0, or 1 when drift remains that it cannot write (a plugin README missing a skill or agent name, a missing plugin README, a bad install command), or 2.
  - `--check` writes nothing, prints one line per difference, exits 0/1/2.
  - `--json` prints `{"written": [...], "drift": [...], "errors": [...]}` on stdout instead of text lines.
  - When `.claude-plugin/marketplace.json` is missing, write mode needs `--marketplace-name` and `--owner` (else exit 2); it then creates `{"name": NAME, "owner": {"name": OWNER}, "metadata": {"description": "Reusable Agent Skills and Plugins for Claude Code"}, "plugins": [...]}`.
- `standalone-plugins.txt`: one plugin name per line; `#` comments and blank lines ignored.

- [ ] **Step 1: Write `standalone-plugins.txt`**

```text
# Plugins that ship from their own marketplace (abhattacherjee/<name>, installed as
# <name>@<name>-repo). They get no catalogue row or marketplace entry here.
# Read by catalogue.py and sync-monorepo.sh.
git-flow
obsidian-brain
```

- [ ] **Step 2: Write the failing tests**

`scripts/test-catalogue.sh`, in the style of `scripts/test-validate-plugin.sh` (`ok`/`bad` counters, `set -euo pipefail`, `TMP=$(mktemp -d)`, trap cleanup, exit 1 when `FAIL>0`). `CAT="${CAT:-$REPO_ROOT/plugins/skill-kit/skills/publish/scripts/catalogue.py}"`.

Fixture builder:

```bash
# fixture <dir>: a clean two-plugin repo that catalogue.py --check accepts once written.
fixture() {
  local r="$1"
  mkdir -p "$r/.claude-plugin" "$r/scripts"
  : > "$r/scripts/install-plugin.sh"
  for p in alpha beta; do
    mkdir -p "$r/plugins/$p/.claude-plugin" "$r/plugins/$p/skills/$p-one" "$r/plugins/$p/agents"
    printf '{"name":"%s","version":"1.0.0","description":"The %s plugin — does things."}\n' "$p" "$p" > "$r/plugins/$p/.claude-plugin/plugin.json"
    printf -- '---\nname: %s-one\n---\n' "$p" > "$r/plugins/$p/skills/$p-one/SKILL.md"
    printf '# %s\n\n<!-- plugin-meta:start -->\n<!-- plugin-meta:end -->\n\nSkill `%s-one`.\n' "$p" "$p" > "$r/plugins/$p/README.md"
  done
  printf '# agent\n' > "$r/plugins/beta/agents/beta-helper.md"
  printf '%s\n' '# beta' '' '<!-- plugin-meta:start -->' '<!-- plugin-meta:end -->' '' 'Skill `beta-one`, agent `beta-helper`.' > "$r/plugins/beta/README.md"
  printf '# Repo\n\nIntro kept.\n\n<!-- catalogue:start -->\n<!-- catalogue:end -->\n\n/plugin install PLUGIN_NAME@demo-market\n\nTail kept.\n' > "$r/README.md"
  printf '{\n  "name": "demo-market",\n  "owner": {"name": "Tester"},\n  "metadata": {"description": "d", "version": "2026.01.01"},\n  "plugins": []\n}\n' > "$r/.claude-plugin/marketplace.json"
}
run() { OUT="$(python3 "$CAT" "$@" 2>&1)" && RC=0 || RC=$?; }
```

Cases (each a separate `ok`/`bad` line; every expected text is a substring of `$OUT`):

1. Fresh fixture: `run --check R` → RC 1 (empty table is drift). Then `run R` → RC 0, `$OUT` contains `WROTE README.md`, `WROTE .claude-plugin/marketplace.json`, `WROTE plugins/alpha/README.md`. Then `run --check R` → RC 0. Then `run R` again → RC 0 and `$OUT` empty (idempotent).
2. After write: README contains the exact row `| [alpha](./plugins/alpha/) | 1.0.0 | 1 | 0 | The alpha plugin — does things. |`; `Intro kept.` and `Tail kept.` lines unchanged (compare `sed -n '1,4p'` and the tail before/after with `cmp`).
3. After write: `python3 -c` loads marketplace.json; `plugins` == `[{"name":"alpha","source":"./plugins/alpha","description":"The alpha plugin — does things.","version":"1.0.0"}, {beta…}]` in that key order; `owner` and `metadata` unchanged; the file contains the literal `—` (not `—`).
4. After write: `plugins/beta/README.md` contains `**Version:** 1.0.0 · **1** skill · **1** agent · **0** commands`.
5. Seeded drift, one fresh written fixture each, `run --check` → RC 1 and the named text:
   - bump alpha plugin.json version to `1.0.1` → `README.md: row alpha: version 1.0.0 != plugin.json 1.0.1` and `marketplace.json: alpha: version` and `plugins/alpha/README.md: meta line`
   - add `plugins/alpha/skills/alpha-two/SKILL.md` → `row alpha: skills 1 != 2` and `plugins/alpha/README.md: does not name skill alpha-two`
   - change alpha description in plugin.json → `row alpha: description`
   - delete the alpha row line from README.md → `README.md: row alpha: missing`
   - add a row `| [ghost](./plugins/ghost/) | 1.0.0 | 0 | 0 | x |` → `README.md: row ghost: no such plugin`
   - edit marketplace.json alpha `source` to `./x` → `marketplace.json: alpha: source`
   - remove `` `beta-helper` `` from beta's README → `does not name agent beta-helper`
   - change README install line to `@other-market` → `README.md: /plugin install PLUGIN_NAME@other-market: marketplace is demo-market`
   - `rm scripts/install-plugin.sh` and add the line `/tmp/x/scripts/install-plugin.sh /tmp/x/plugins/PLUGIN_NAME` to README → `scripts/install-plugin.sh: does not exist`
6. Fail closed, each `run --check` → RC 2 and the named text:
   - remove `<!-- catalogue:end -->` → `README.md: needs exactly one <!-- catalogue:end -->`
   - duplicate the start marker → `needs exactly one <!-- catalogue:start -->`
   - write `{` into alpha's plugin.json → `plugins/alpha/.claude-plugin/plugin.json:` and `Expecting`
   - drop `version` from alpha's plugin.json → `'version' missing or empty`
   - set alpha's `name` to `alpha2` → `name alpha2 does not match directory alpha`
   - description containing `a | b` → `description contains '|' or a newline`
   - `mkdir R/plugins/stray` → `plugins/stray/.claude-plugin/plugin.json: missing`
   - remove `R/plugins` → `no plugins/ directory`
   - remove alpha's meta markers → in `--check` RC 1 `plugins/alpha/README.md: no meta line`; in write mode RC 0 and the meta block is inserted after the first `# ` heading line
7. Standalone: add `plugins/git-flow/` with no plugin.json → `run --check` RC 0 (skipped, not reported).
8. CRLF: convert the written README with `perl -pi -e 's/\n/\r\n/'`, add one row of drift, `run R` → RC 0 and every line outside the block still ends in `\r\n` (`grep -c $'\r$'` equals the original count).
9. Marketplace missing: `rm` it; `run R` → RC 2 `marketplace.json is missing; pass --marketplace-name and --owner`; `run --marketplace-name m --owner o R` → RC 0 and the file has `"name": "m"`.
10. `--json`: on seeded drift, `run --check --json R` → RC 1 and `python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["drift"] and d["errors"]==[]'` succeeds on `$OUT`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `bash scripts/test-catalogue.sh`
Expected: FAIL (catalogue.py does not exist yet), non-zero exit.

- [ ] **Step 4: Write `catalogue.py`**

```python
#!/usr/bin/env python3
"""catalogue.py — write or check a plugin monorepo's catalogue (#190).

Each plugins/<name>/.claude-plugin/plugin.json is the only source of a
plugin's name, version and description. From it, and from the skills/,
agents/ and commands/ directories, this writes:

  * the root README table between <!-- catalogue:start --> and
    <!-- catalogue:end --> (text outside the markers is never touched);
  * .claude-plugin/marketplace.json's plugins[] (every other key is kept);
  * one meta line in each plugins/<name>/README.md between
    <!-- plugin-meta:start --> and <!-- plugin-meta:end -->.

--check writes nothing and reports every difference. It also checks what
cannot be generated: each plugin README must name each of its skills and
agents, and the root README's install commands must use this marketplace.

Exit: 0 clean (or written), 1 drift (or drift left that needs a hand edit),
2 cannot run. It fails closed: a missing or repeated marker, a bad
plugin.json, or a stray plugins/ directory is exit 2, never a skip.
"""
import argparse
import json
import re
import sys
from pathlib import Path

CAT_START, CAT_END = "<!-- catalogue:start -->", "<!-- catalogue:end -->"
META_START, META_END = "<!-- plugin-meta:start -->", "<!-- plugin-meta:end -->"
HEADER = ("| Plugin | Version | Skills | Commands | Description |",
          "|--------|---------|--------|----------|-------------|")
ROW_RE = re.compile(r"^\| \[([^\]]+)\]\(\./plugins/[^)]*\) \| ([^|]*) \| ([^|]*) \| ([^|]*) \| (.*) \|$")
INSTALL_RE = re.compile(r"/plugin (?:un)?install ([A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+)")
INSTALL_SCRIPT_RE = re.compile(r"scripts/install-plugin\.sh")
DEFAULT_MARKET_DESC = "Reusable Agent Skills and Plugins for Claude Code"


class CannotRun(Exception):
    pass


def standalone_plugins():
    f = Path(__file__).with_name("standalone-plugins.txt")
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        raise CannotRun(f"{f}: {e}")
    return {l.strip() for l in lines if l.strip() and not l.strip().startswith("#")}


def plural(n, word):
    return f"**{n}** {word}{'' if n == 1 else 's'}"


def load_plugins(repo):
    pdir = repo / "plugins"
    if not pdir.is_dir():
        raise CannotRun(f"{repo}: no plugins/ directory")
    skip = standalone_plugins()
    plugins = []
    for d in sorted(p for p in pdir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if d.name in skip:
            continue
        mf = d / ".claude-plugin" / "plugin.json"
        rel = mf.relative_to(repo)
        if not mf.is_file():
            raise CannotRun(f"{rel}: missing")
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CannotRun(f"{rel}: {e}")
        if not isinstance(m, dict):
            raise CannotRun(f"{rel}: not a JSON object")
        for k in ("name", "version", "description"):
            if not isinstance(m.get(k), str) or not m[k].strip():
                raise CannotRun(f"{rel}: '{k}' missing or empty")
        if m["name"] != d.name:
            raise CannotRun(f"{rel}: name {m['name']} does not match directory {d.name}")
        if "|" in m["description"] or "\n" in m["description"]:
            raise CannotRun(f"{rel}: description contains '|' or a newline; it cannot sit in a table row")
        plugins.append({
            "name": m["name"], "version": m["version"], "description": m["description"],
            "skills": sorted(s.parent.name for s in d.glob("skills/*/SKILL.md")),
            "agents": sorted(a.stem for a in d.glob("agents/*.md")),
            "commands": sorted(c.stem for c in d.glob("commands/*.md")),
            "dir": d,
        })
    return plugins


def split(text, start, end, where):
    if text.count(start) != 1:
        raise CannotRun(f"{where}: needs exactly one {start}")
    if text.count(end) != 1:
        raise CannotRun(f"{where}: needs exactly one {end}")
    a = text.index(start) + len(start)
    b = text.index(end)
    if b < a:
        raise CannotRun(f"{where}: {end} comes before {start}")
    return text[:a], text[a:b], text[b:]


def newline_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def row(p):
    return (f"| [{p['name']}](./plugins/{p['name']}/) | {p['version']} | "
            f"{len(p['skills'])} | {len(p['commands'])} | {p['description']} |")


def meta(p):
    return (f"**Version:** {p['version']} · {plural(len(p['skills']), 'skill')} · "
            f"{plural(len(p['agents']), 'agent')} · {plural(len(p['commands']), 'command')}")


def readme_block(plugins, nl):
    return nl + nl.join(HEADER + tuple(row(p) for p in plugins)) + nl


def readme_drift(block, plugins):
    """Return drift lines for the README table block."""
    want = {p["name"]: p for p in plugins}
    have = {}
    for line in block.replace("\r\n", "\n").split("\n"):
        m = ROW_RE.match(line)
        if m:
            have[m.group(1)] = [g.strip() for g in m.groups()[1:]]
    out = []
    for name, p in want.items():
        if name not in have:
            out.append(f"README.md: row {name}: missing")
            continue
        ver, sk, cm, desc = have[name]
        if ver != p["version"]:
            out.append(f"README.md: row {name}: version {ver} != plugin.json {p['version']}")
        if sk != str(len(p["skills"])):
            out.append(f"README.md: row {name}: skills {sk} != {len(p['skills'])}")
        if cm != str(len(p["commands"])):
            out.append(f"README.md: row {name}: commands {cm} != {len(p['commands'])}")
        if desc != p["description"]:
            out.append(f"README.md: row {name}: description differs from plugin.json")
    for name in have:
        if name not in want:
            out.append(f"README.md: row {name}: no such plugin")
    return out


def market_entries(plugins):
    return [{"name": p["name"], "source": f"./plugins/{p['name']}",
             "description": p["description"], "version": p["version"]} for p in plugins]


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def market_drift(current, entries):
    out = []
    have = {e.get("name"): e for e in current.get("plugins", []) if isinstance(e, dict)}
    for e in entries:
        h = have.get(e["name"])
        if h is None:
            out.append(f"marketplace.json: {e['name']}: missing")
            continue
        for k in ("source", "description", "version"):
            if h.get(k) != e[k]:
                out.append(f"marketplace.json: {e['name']}: {k} differs from plugin.json")
    for name in have:
        if name not in {e["name"] for e in entries}:
            out.append(f"marketplace.json: {name}: no such plugin")
    return out


def install_drift(readme, names, market, repo):
    out = []
    skip = standalone_plugins()
    for m in INSTALL_RE.finditer(readme):
        x, mk = m.group(1), m.group(2)
        if x in skip and mk == f"{x}-repo":
            continue
        if mk != market:
            out.append(f"README.md: {m.group(0)}: marketplace is {market}")
        if x != "PLUGIN_NAME" and x not in names:
            out.append(f"README.md: {m.group(0)}: no plugin {x}")
    if INSTALL_SCRIPT_RE.search(readme) and not (repo / "scripts" / "install-plugin.sh").is_file():
        out.append("README.md: names scripts/install-plugin.sh: scripts/install-plugin.sh does not exist")
    return out


def name_drift(p, text):
    out = []
    rel = f"plugins/{p['name']}/README.md"
    for kind, names in (("skill", p["skills"]), ("agent", p["agents"])):
        for n in names:
            if not re.search(r"(?<![A-Za-z0-9-])" + re.escape(n) + r"(?![A-Za-z0-9-])", text):
                out.append(f"{rel}: does not name {kind} {n}")
    return out


def run(repo, check, market_name, owner):
    written, drift = [], []
    plugins = load_plugins(repo)
    names = {p["name"] for p in plugins}

    # Root README
    rp = repo / "README.md"
    try:
        readme = rp.read_text(encoding="utf-8")
    except OSError as e:
        raise CannotRun(f"README.md: {e}")
    nl = newline_of(readme)
    head, block, tail = split(readme, CAT_START, CAT_END, "README.md")
    new_readme = head + readme_block(plugins, nl) + tail

    # Marketplace
    mp = repo / ".claude-plugin" / "marketplace.json"
    if mp.is_file():
        try:
            market = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CannotRun(f".claude-plugin/marketplace.json: {e}")
        if not isinstance(market, dict) or not isinstance(market.get("name"), str):
            raise CannotRun(".claude-plugin/marketplace.json: no top-level name")
    else:
        if not (market_name and owner):
            raise CannotRun(".claude-plugin/marketplace.json is missing; pass --marketplace-name and --owner")
        market = {"name": market_name, "owner": {"name": owner},
                  "metadata": {"description": DEFAULT_MARKET_DESC}, "plugins": []}
    entries = market_entries(plugins)
    new_market = dict(market)
    new_market["plugins"] = entries

    # Plugin READMEs
    plugin_writes = []
    for p in plugins:
        f = p["dir"] / "README.md"
        rel = f"plugins/{p['name']}/README.md"
        if not f.is_file():
            drift.append(f"{rel}: missing")
            continue
        text = f.read_text(encoding="utf-8")
        pnl = newline_of(text)
        if META_START not in text and META_END not in text:
            if check:
                drift.append(f"{rel}: no meta line ({META_START} … {META_END})")
                drift.extend(name_drift(p, text))
                continue
            lines = text.split(pnl)
            at = next((i + 1 for i, l in enumerate(lines) if l.startswith("# ")), 0)
            lines[at:at] = ["", META_START, meta(p), META_END]
            new = pnl.join(lines)
        else:
            h, b, t = split(text, META_START, META_END, rel)
            if b.strip() != meta(p):
                drift.append(f"{rel}: meta line differs ({meta(p)})")
            new = h + pnl + meta(p) + pnl + t
        drift.extend(name_drift(p, new))
        if new != text:
            plugin_writes.append((f, new, rel))

    drift = readme_drift(block, plugins) + (market_drift(market, entries) if mp.is_file() else ["marketplace.json: missing"]) + drift
    if mp.is_file() and not market_drift(market, entries) and mp.read_text(encoding="utf-8") != dump(new_market):
        drift.append("marketplace.json: formatting differs from catalogue.py output")
    if new_readme != readme and not readme_drift(block, plugins):
        drift.append("README.md: catalogue table formatting differs from catalogue.py output")
    drift.extend(install_drift(new_readme, names, new_market["name"], repo))

    if check:
        return written, drift

    if new_readme != readme:
        rp.write_text(new_readme, encoding="utf-8", newline="")
        written.append("README.md")
    if not mp.is_file() or mp.read_text(encoding="utf-8") != dump(new_market):
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(dump(new_market), encoding="utf-8")
        written.append(".claude-plugin/marketplace.json")
    for f, new, rel in plugin_writes:
        f.write_text(new, encoding="utf-8", newline="")
        written.append(rel)
    # Only what a write cannot fix is left: names, missing READMEs, install lines.
    left = [d for d in drift if " does not name " in d or d.endswith(": missing") and d.startswith("plugins/")
            or d.startswith("README.md: /plugin") or "install-plugin.sh" in d]
    return written, left


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--marketplace-name")
    ap.add_argument("--owner")
    a = ap.parse_args(argv)
    try:
        written, drift = run(a.repo.resolve(), a.check, a.marketplace_name, a.owner)
        errors = []
    except CannotRun as e:
        written, drift, errors = [], [], [str(e)]
    if a.json:
        print(json.dumps({"written": written, "drift": drift, "errors": errors}, indent=2))
    else:
        for w in written:
            print(f"WROTE {w}")
        for d in drift:
            print(d)
        for e in errors:
            print(f"catalogue.py: cannot run: {e}", file=sys.stderr)
    return 2 if errors else (1 if drift else 0)


if __name__ == "__main__":
    sys.exit(main())
```

Notes for the implementer: this is a sketch. Fix what is wrong and say so. In particular check that the write-mode `left` filter and the check-mode drift lines match the test texts exactly, and that writing `newline=""` keeps CRLF.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bash scripts/test-catalogue.sh`
Expected: every case PASS, exit 0. Then mutate once in a scratch copy (drop the `count(start) != 1` check) and confirm case 6 fails.

- [ ] **Step 6: Commit**

```bash
chmod +x plugins/skill-kit/skills/publish/scripts/catalogue.py scripts/test-catalogue.sh
git add plugins/skill-kit/skills/publish/scripts/catalogue.py plugins/skill-kit/skills/publish/scripts/standalone-plugins.txt scripts/test-catalogue.sh
./scripts/commit-preflight.sh
git commit -m "skill-kit publish: catalogue.py writes and checks the plugin catalogue (#190)"
```

### Task 2: `check-doc-refs.py` — links, repo paths and `plugin:skill` names

**Files:**
- Create: `scripts/check-doc-refs.py`
- Create: `scripts/test-check-doc-refs.sh`

**Interfaces:**
- Produces: CLI `check-doc-refs.py [<repo>]` (default: the repo the script lives in). Prints `file:line: token: reason` per broken reference. Exit 0/1/2. `DOC_FILES` env var is not supported; the file list is fixed in the script.

- [ ] **Step 1: Write the failing tests**

`scripts/test-check-doc-refs.sh`, same harness style. Fixture: a repo with `README.md CONTRIBUTING.md LOCAL-TESTING.md AGENTS.md CLAUDE.md`, `plugins/kit/.claude-plugin/plugin.json`, `plugins/kit/skills/publish/SKILL.md`, `plugins/kit/skills/publish/scripts/run.sh`, `plugins/kit/agents/helper.md`, `plugins/kit/README.md`, `scripts/real.sh`, `docs/x.md`.

Cases:
1. Clean fixture (each root doc holds one valid reference of each kind: `[x](./docs/x.md)`, `` `scripts/real.sh` ``, `` `kit:publish` ``, `` `/kit:helper` ``) → RC 0, no output.
2. R1: `[gone](./docs/gone.md)` in README → RC 1, `README.md:` and `./docs/gone.md`. `[ok](https://example.com)`, `[a](#anchor)` and `[m](mailto:a@b)` → not reported. `[ok](./docs/x.md#part)` → not reported.
3. R2: `` `plugins/kit/skills/nope/` `` → RC 1. `` `plugins/<group>/skills/<name>/` `` → not reported (matches one path). `` `plugins/<group>/skills/zzz/` `` → reported. `` `./scripts/real.sh` `` → not reported. `` `scripts/real.sh --flag` `` (has a space) → not reported.
4. R2 in a plugin README: `` `scripts/run.sh` `` in `plugins/kit/README.md` → not reported (resolves in a skill dir of that plugin); the same token in root `README.md` → reported.
5. R3: `` `kit:nothing` `` → RC 1, `kit:nothing: kit has no skill, agent or command named nothing`. `` `git-flow:feature` `` and `` `pr-review-toolkit:code-reviewer` `` → not reported.
6. Fenced block: a ```` ``` ```` block holding `` `scripts/gone.sh` `` and `[x](./gone.md)` → not reported; the same tokens after the fence closes → reported.
7. Exit 2: delete `LOCAL-TESTING.md` → RC 2 and `LOCAL-TESTING.md: missing`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bash scripts/test-check-doc-refs.sh` — Expected: FAIL, non-zero.

- [ ] **Step 3: Write `check-doc-refs.py`**

```python
#!/usr/bin/env python3
"""check-doc-refs.py — every path, link and plugin:skill name in the current docs must exist (#190).

Files: README.md, CONTRIBUTING.md, LOCAL-TESTING.md, AGENTS.md, CLAUDE.md and
plugins/*/README.md. Dated plans and specs under docs/ and CHANGELOGs are
history, so they are not checked.

Rules, outside fenced code blocks:
  R1  a relative Markdown link target must exist, relative to the file;
  R2  an inline-code token starting with plugins/, scripts/, .github/,
      .claude-plugin/ or docs/ must exist relative to the repo root (in a
      plugin README also relative to the plugin and each of its skill
      directories); <anything> and * match one path segment;
  R3  an inline-code /plugin:name or plugin:name, where plugin is one of
      plugins/*, must name one of its skills, agents or commands.

Blind spots: bare file names (`record.sh`), anything inside fenced blocks,
tokens with spaces, and paths in a user's own project are not checked.

Exit: 0 clean, 1 broken references (file:line: token: reason), 2 cannot run.
"""
import re
import sys
from pathlib import Path

ROOT_DOCS = ["README.md", "CONTRIBUTING.md", "LOCAL-TESTING.md", "AGENTS.md", "CLAUDE.md"]
LINK = re.compile(r"\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`\n]+)`")
PREFIXES = ("plugins/", "scripts/", ".github/", ".claude-plugin/", "docs/")
NS = re.compile(r"^/?([a-z0-9-]+):([a-z0-9-]+)$")
FENCE = re.compile(r"^\s*(```|~~~)")


def exists(bases, token):
    t = token[2:] if token.startswith("./") else token
    pattern = re.sub(r"<[^>]*>", "*", t).rstrip("/")
    for b in bases:
        if "*" in pattern:
            if any(b.glob(pattern)):
                return True
        elif (b / pattern).exists():
            return True
    return False


def plugin_names(repo):
    out = {}
    for d in (repo / "plugins").glob("*/"):
        names = {s.parent.name for s in d.glob("skills/*/SKILL.md")}
        names |= {a.stem for a in d.glob("agents/*.md")}
        names |= {c.stem for c in d.glob("commands/*.md")}
        out[d.name] = names
    return out


def check_file(repo, f, names):
    rel = f.relative_to(repo)
    bases = [repo]
    if rel.parts[0] == "plugins":
        pd = repo / "plugins" / rel.parts[1]
        bases += [pd] + [s for s in pd.glob("skills/*/") if s.is_dir()]
    out, fenced = [], False
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for m in LINK.finditer(line):
            t = m.group(1)
            if t.startswith(("http://", "https://", "mailto:", "#", "<")):
                continue
            target = t.split("#", 1)[0]
            if target and not (f.parent / target).exists():
                out.append(f"{rel}:{i}: {t}: link target does not exist")
        for m in CODE.finditer(line):
            t = m.group(1)
            if " " in t:
                continue
            bare = t[2:] if t.startswith("./") else t
            if bare.startswith(PREFIXES):
                if not exists(bases, t):
                    out.append(f"{rel}:{i}: {t}: no such path")
                continue
            n = NS.match(t)
            if n and n.group(1) in names and n.group(2) not in names[n.group(1)]:
                out.append(f"{rel}:{i}: {t}: {n.group(1)} has no skill, agent or command named {n.group(2)}")
    return out


def main(argv):
    repo = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    files = []
    for d in ROOT_DOCS:
        if not (repo / d).is_file():
            print(f"check-doc-refs.py: cannot run: {d}: missing", file=sys.stderr)
            return 2
        files.append(repo / d)
    files += sorted((repo / "plugins").glob("*/README.md"))
    names = plugin_names(repo)
    broken = []
    try:
        for f in files:
            broken += check_file(repo, f, names)
    except (OSError, UnicodeDecodeError) as e:
        print(f"check-doc-refs.py: cannot run: {e}", file=sys.stderr)
        return 2
    for b in broken:
        print(b)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run the tests to verify they pass** — `bash scripts/test-check-doc-refs.sh`, all PASS.

- [ ] **Step 5: Commit**

```bash
chmod +x scripts/check-doc-refs.py scripts/test-check-doc-refs.sh
git add scripts/check-doc-refs.py scripts/test-check-doc-refs.sh
./scripts/commit-preflight.sh
git commit -m "scripts: check-doc-refs.py checks links, repo paths and plugin:skill names (#190)"
```

### Task 3: Migrate the catalogue and fix every doc finding

**Files:**
- Modify: the 13 `plugins/<deprecated>/.claude-plugin/plugin.json` whose `marketplace.json` description starts `Deprecated:` (adversarial-review, context-bar, context-shield, custom-statusline, deep-review, figma-ui-designer, product-video-creation, skill-authoring, skill-publishing, smart-screen-recorder, spec-creator, spec-implement, spec-review, statusline-creator — count them from `marketplace.json`; the number in this list is not authoritative).
- Modify: `README.md` (markers around the table), every `plugins/*/README.md` (meta line), `plugins/smart-screen-recorder/README.md` (its five agents), `.claude-plugin/marketplace.json`, `LOCAL-TESTING.md`, and every file `check-doc-refs.py` reports.
- Modify: every `plugins/*/.claude-plugin/plugin.json` except skill-kit (patch bump: the README changed) and each plugin `CHANGELOG.md`.

- [ ] **Step 1: Move each `Deprecated: …` description from marketplace.json into that plugin's plugin.json.** One Python one-off in the scratchpad: for each marketplace entry whose description differs from plugin.json, set plugin.json's description to the marketplace one; print each change. Keep plugin.json's own key order and 2-space indent.

- [ ] **Step 2: Patch-bump every plugin except skill-kit** (skill-kit gets 1.1.0 in Task 5) and add a CHANGELOG entry at the top of each plugin's `CHANGELOG.md`, inside the existing structure:

```markdown
## [X.Y.Z] - 2026-10-05

### Changed
- The README states the plugin version and its skill, agent and command counts, written by `catalogue.py` (#190).
```

For the deprecated ones add a second line: `- plugin.json carries the "Deprecated: …" description that only marketplace.json had (#190).` If a skill-level `metadata.version` must move with the plugin version under this repo's rules, follow `validate-plugin.sh`; it is the authority.

- [ ] **Step 3: Put the markers in `README.md`**: `<!-- catalogue:start -->` on its own line directly above the `| Plugin | Version |…` header line and `<!-- catalogue:end -->` directly below the last row.

- [ ] **Step 4: Run** `python3 plugins/skill-kit/skills/publish/scripts/catalogue.py .` It inserts the meta line in each plugin README and rewrites the table and marketplace. Read the full `git diff` of `README.md` and `.claude-plugin/marketplace.json`: the only changes must be the new versions and the meta lines. Any other change (ordering, escaping, a description) is a bug in Task 1's code — fix it there with a test, not here.

- [ ] **Step 5: Fix what `catalogue.py --check .` still reports by hand** (expected: smart-screen-recorder's README does not name its agents `zoom-qa-verifier`, `voiceover-timing-fixer`, `demo-storyteller`, `demo-director`, `demo-post-production-editor`). Add one line per agent to its agents list with a one-line role taken from the agent file's own description.

- [ ] **Step 6: Run** `python3 scripts/check-doc-refs.py` **and fix every finding** by editing the doc to the real path, skill or agent name. Where a finding is a path in a user's project or an example, put it in a fenced block or rewrite it so it is plainly an example. Also fix `LOCAL-TESTING.md`'s example branch `feature/159-review-plugin` (use `feature/<N>-<slug>`). Record each fix in the commit body.

- [ ] **Step 7: Verify**: `python3 plugins/skill-kit/skills/publish/scripts/catalogue.py --check .` → exit 0; `python3 scripts/check-doc-refs.py` → exit 0; `for p in plugins/*/; do ./scripts/validate-plugin.sh "$p"; done` → all PASS.

- [ ] **Step 8: Commit** (one commit; the preflight validates every staged plugin)

```bash
git add README.md LOCAL-TESTING.md .claude-plugin/marketplace.json plugins/*/README.md plugins/*/CHANGELOG.md plugins/*/.claude-plugin/plugin.json <each other fixed doc by name>
./scripts/commit-preflight.sh
git commit -m "docs: catalogue from plugin.json, meta lines, and every broken doc reference fixed (#190)"
```

### Task 4: `sync-monorepo.sh` — plugin-only mode and one catalogue writer

**Files:**
- Modify: `plugins/skill-kit/skills/publish/scripts/_lib.sh:615-686` (drop `refuse_if_plugin_only_monorepo`; keep `is_plugin_only_monorepo`, `has_top_level_skill_dirs`, `list_top_level_candidates`; rewrite the section comment)
- Modify: `plugins/skill-kit/skills/publish/scripts/sync-monorepo.sh` (`:191` refusal; `:199` `STANDALONE_PLUGINS`; `:1197-1255` `--add-plugin` copy; `:1530-1600` plugin section; `:1913-1967` marketplace; the scripts-copy block `:1881-1910`)
- Modify: `plugins/skill-kit/skills/publish/scripts/validate-pre-sync.sh:96-98`
- Modify: `plugins/skill-kit/skills/publish/references/monorepo-readme-template.md`, `references/workflow-monorepo.yml`
- Modify: `scripts/test-sync-hygiene.sh` (the #167 plugin-only section near `:5782-5900`, plus any assertion the marketplace change moves)

**Interfaces:**
- Consumes: `catalogue.py` CLI from Task 1; `standalone-plugins.txt`.
- Produces: plugin-only behaviour per the spec's section 4 table, with `--json` output `{"layout":"plugin-only","validated":N,"catalogue":"written|clean|drift"}`.

- [ ] **Step 1: Write the failing tests** in `scripts/test-sync-hygiene.sh`, replacing the #167 "refused in every mode" cases. Use the existing plugin-only fixture builder in that section, give each fixture plugin a README naming its skill, and add README markers. Cases:
  1. plain sync → rc 0; README table and marketplace.json now list the fixture plugin; every other file byte-identical (tree digest excluding `README.md`, `.claude-plugin/marketplace.json`, `plugins/*/README.md`); no `CHANGELOG.md`, workflow, `CONTRIBUTING.md` or `scripts/` created.
  2. `--dry-run` → rc 0, prints the drift lines, tree digest identical.
  3. `--skills x`, `--add x`, `--init` → each rc 1, message names the mode, tree digest identical.
  4. one fixture plugin made invalid (skill without "Use when:") → plain sync rc 1, names the plugin, tree digest identical (nothing written).
  5. `--add-plugin` of a valid `./build/<n>/` → rc 0, plugin copied, row and marketplace entry present.
  6. `--json` plain → stdout parses, `layout == "plugin-only"`, `catalogue == "written"`; second run `catalogue == "clean"`.
  7. the #167 symlink fixture (a top-level symlink to a dir holding SKILL.md) is still plugin-only: plain sync writes only the catalogue (digest check as case 1).
  8. `validate-pre-sync.sh` on a clean plugin-only fixture → rc 0; on a seeded drift → rc 1 with the drift line; on an invalid plugin → rc 1.
  9. Mixed layout (existing fixtures): marketplace.json is now written by `catalogue.py` — assert valid JSON when a plugin description contains `"` and `\` (this failed before: string-built JSON).

- [ ] **Step 2: Run to verify they fail**: `bash scripts/test-sync-hygiene.sh 2>&1 | tail -20` → the new cases FAIL.

- [ ] **Step 3: Implement**
  - `STANDALONE_PLUGINS` is read from `standalone-plugins.txt` (`grep -v '^#' | grep -v '^$'`, joined with spaces). Fail with exit 1 if the file is missing.
  - Extract the `--add-plugin` copy (`:1197-1255`) into `add_plugin_from_build` so both paths call it.
  - At `:191`, replace the refusal with: `if is_plugin_only_monorepo "$MONOREPO_DIR"; then sync_plugin_only; fi` where `sync_plugin_only` (defined above it) does, in order: refuse `--skills`/`--add` ("plugin-only monorepo has no top-level skills; edit plugins/<group>/skills/<name>/ and run sync"), refuse `--init` ("already initialised: it has plugins/"); with `--add-plugin`, validate `./build/<n>/`; validate every non-standalone `plugins/*/` with `"$SCRIPT_DIR/validate-plugin.sh"` — any failure prints the plugin names and exits 1 before any write; then `add_plugin_from_build` (or `WOULD ADD` on `--dry-run`); then `python3 "$SCRIPT_DIR/catalogue.py" [--check] "$MONOREPO_DIR"`. Map the catalogue exit: 0 → done; 1 on `--dry-run` → print its lines and exit 0; 1 on a write → print "catalogue written; these need a hand edit:" plus its lines and exit 1; 2 → exit 1. It always `exit`s, so nothing below `:191` runs for this layout.
  - Mixed/top-level layouts: the template's plugin table is replaced by the two markers (keep the standalone notes and the install section), and the marketplace block (`:1913-1967`) is replaced by one `catalogue.py --marketplace-name claude-code-skills --owner "$AUTHOR"` call after README.md is written (`--check` under `--dry-run`). Keep the existing `PLUGIN_COUNT -gt 0` guard. Treat a catalogue exit as above.
  - Copy `catalogue.py` and `standalone-plugins.txt` into the consumer's `scripts/` beside `validate-plugin.sh` (same block style as `:1881-1910`), and add `python3 scripts/catalogue.py --check .` as a step of the `validate-plugins` job in `references/workflow-monorepo.yml`.
  - `validate-pre-sync.sh:96-98`: on a plugin-only repo, validate every plugin and run `catalogue.py --check`; exit 1 if either fails; `--json` keeps its current shape plus `"layout": "plugin-only"`.
  - Update the `_lib.sh` section comment: plugin-only monorepos are synced by `sync_plugin_only` (#190), not refused.

- [ ] **Step 4: Run** `bash scripts/test-sync-hygiene.sh` (whole suite, foreground) → all PASS; `bash plugins/skill-kit/tests/run-tests.sh` → PASS. Any pre-existing assertion you changed must be listed in the report with why its old expectation was wrong.

- [ ] **Step 5: Dogfood on this repo, in a scratch copy** (`git archive HEAD | tar -x -C <scratch>`): `plugins/skill-kit/skills/publish/scripts/sync-monorepo.sh --dry-run <scratch>` → rc 0, no drift; plain → rc 0 and the scratch tree digest unchanged (the catalogue is already clean).

- [ ] **Step 6: Commit**

```bash
git add plugins/skill-kit/skills/publish/scripts/_lib.sh plugins/skill-kit/skills/publish/scripts/sync-monorepo.sh plugins/skill-kit/skills/publish/scripts/validate-pre-sync.sh plugins/skill-kit/skills/publish/references/monorepo-readme-template.md plugins/skill-kit/skills/publish/references/workflow-monorepo.yml scripts/test-sync-hygiene.sh
./scripts/commit-preflight.sh
git commit -m "skill-kit publish: sync a plugin-only monorepo; catalogue.py is the one catalogue writer (#190)"
```

### Task 5: Wire the guard into CI and preflight; docs and versions

**Files:**
- Create: `scripts/check-docs.sh`
- Modify: `scripts/commit-preflight.sh` (before the `SKIP_TESTS` block, so `--docs-only` runs it too)
- Modify: `.github/workflows/validate-skill.yml` (new `docs-drift` job)
- Modify: `plugins/skill-kit/skills/publish/SKILL.md` (plugin-only section; catalogue.py), `plugins/skill-kit/.claude-plugin/plugin.json` → `1.1.0`, `plugins/skill-kit/CHANGELOG.md`, `plugins/skill-kit/skills/publish/CHANGELOG.md` (+ the publish skill's `metadata.version` minor bump), root `CHANGELOG.md` `[Unreleased]`, `CONTRIBUTING.md` (one paragraph: the catalogue is generated; run `catalogue.py .` after changing a plugin.json; `scripts/check-docs.sh` runs in preflight and CI).

- [ ] **Step 1: Write `scripts/check-docs.sh`**

```bash
#!/usr/bin/env bash
# check-docs.sh — the docs drift guard (#190): the catalogue matches every
# plugin.json, and every link, repo path and plugin:skill name in the current
# docs exists. Exit 0 clean, 1 drift, 2 a check could not run.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAT="$ROOT/plugins/skill-kit/skills/publish/scripts/catalogue.py"
[[ -f "$CAT" ]] || { echo "check-docs.sh: $CAT is missing" >&2; exit 2; }
rc=0
python3 "$CAT" --check "$ROOT"; r=$?; (( r > rc )) && rc=$r
python3 "$ROOT/scripts/check-doc-refs.py" "$ROOT"; r=$?; (( r > rc )) && rc=$r
(( rc == 0 )) && echo "check-docs.sh: catalogue and doc references are clean"
exit "$rc"
```

- [ ] **Step 2: Forced failure first.** In a scratch copy: seed a version bump in one plugin.json → `scripts/check-docs.sh` exit 1; `rm` catalogue.py → exit 2; `rm scripts/check-doc-refs.py` → non-zero. Record the three exit codes.

- [ ] **Step 3: Preflight.** Insert, right after the staged-files listing and before `# Handle skip tests mode`:

```bash
# ── Docs drift guard (always runs, docs-only too) ─────────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📚 Running docs drift guard..."
if ! ./scripts/check-docs.sh; then
    echo "❌ Docs drift guard failed — run plugins/skill-kit/skills/publish/scripts/catalogue.py . and fix the lines above"
    rm -f "$TOKEN_FILE"
    exit 1
fi
echo ""
```

Prove it without committing: seed a drift in a committed, clean file in the working tree, stage any file, run `./scripts/commit-preflight.sh --docs-only` and confirm exit 1. Then restore the seeded file with `git checkout -- <file>` and unstage.

- [ ] **Step 4: CI.** Add to `.github/workflows/validate-skill.yml`, matching the other jobs' shape:

```yaml
  docs-drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Docs drift guard
        run: ./scripts/check-docs.sh
      - name: catalogue.py tests
        run: bash scripts/test-catalogue.sh
      - name: check-doc-refs.py tests
        run: bash scripts/test-check-doc-refs.sh
```

Use the same `actions/checkout` version the file already uses. Run `bash scripts/test-ci-skill-detect.sh` afterwards; it parses this workflow.

- [ ] **Step 5: Docs and versions.** skill-kit `1.1.0` and the publish skill minor bump; publish `SKILL.md` gets a "Plugin-only monorepos" section stating the mode table in plain words (plain sync validates and writes only the catalogue; `--dry-run` checks; `--add-plugin` works; `--skills`, `--add`, `--init` are refused) and how to run `catalogue.py`; CHANGELOG entries for skill-kit, publish and root `[Unreleased]` (Added: catalogue.py, check-doc-refs.py, check-docs.sh, docs-drift CI job, preflight guard; Changed: plugin-only sync, marketplace.json written by catalogue.py, Deprecated descriptions live in plugin.json; Closes #2 and #84). Then `python3 plugins/skill-kit/skills/publish/scripts/catalogue.py .` (skill-kit's version changed) and `scripts/check-docs.sh` → exit 0.

- [ ] **Step 6: Full verification**: every `scripts/test-*.sh`, `plugins/skill-kit/tests/run-tests.sh`, `validate-plugin.sh` on every plugin, `validate-skill.sh` on the publish skill, `scripts/check-docs.sh`.

- [ ] **Step 7: Commit**

```bash
chmod +x scripts/check-docs.sh
git add scripts/check-docs.sh scripts/commit-preflight.sh .github/workflows/validate-skill.yml plugins/skill-kit/skills/publish/SKILL.md plugins/skill-kit/.claude-plugin/plugin.json plugins/skill-kit/CHANGELOG.md plugins/skill-kit/skills/publish/CHANGELOG.md CHANGELOG.md CONTRIBUTING.md README.md .claude-plugin/marketplace.json plugins/skill-kit/README.md
./scripts/commit-preflight.sh
git commit -m "docs drift guard in CI and commit-preflight; skill-kit 1.1.0 (#190)"
```

## Pre-review self-check (every implementer, before reporting done)

One line per class, each with the cases found and the test for each, or "none" plus what was checked:
1. Fail-open paths (an exception, a missing file or a skipped plugin that ends as exit 0).
2. Exit codes (a check that exits 0 when it found drift or could not run).
3. Date boundaries (CHANGELOG dates; marketplace `metadata.version` must not change on a clean run).
4. Doc counts (every number in a CHANGELOG, SKILL.md or comment, counted from the diff).
5. Broken Markdown (table rows, CHANGELOG entries and list items inside their blocks).
