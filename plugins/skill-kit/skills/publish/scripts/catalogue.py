#!/usr/bin/env python3
"""catalogue.py — write or check a plugin monorepo's catalogue (#190).

Each plugins/<name>/.claude-plugin/plugin.json is the only source of a
plugin's name, version and description. From it, and from the skills/,
agents/ and commands/ directories, this writes:

  * the root README table between <!-- catalogue:start --> and
    <!-- catalogue:end --> (text outside the markers is never touched);
  * .claude-plugin/marketplace.json's plugins[] (every other key is kept);
  * one meta line in each plugins/<name>/README.md between
    <!-- plugin-meta:start --> and <!-- plugin-meta:end --> (a README with
    no markers gets them after its first "# " heading).

--check writes nothing and reports every difference, including any change
a write would make. Both modes also check what cannot be generated: each
plugin README must name each of its skills and agents (as `name`,
plugin:name or /name), and the root README's install commands must use this
marketplace. A write fixes what it can and reports the rest.

--validate-plugins only loads and checks every plugin (plugin.json, the
skills/, agents/ and commands/ directories, and the write targets), without
needing the README markers. sync-monorepo.sh runs it before its first write.

Plugins listed in standalone-plugins.txt (next to this file) are skipped.

Exit: 0 clean (or written), 1 drift (or, after a write, drift left that
needs a hand edit), 2 cannot run. It fails closed: a missing or repeated
marker, a bad plugin.json, name or version, a stray plugins/ directory, a
file or directory it cannot read, or a write target or plugin directory
that is a symlink or resolves outside the repo is exit 2, never a skip.

A write reads and checks every file first, then writes each changed file to
a temp file beside it, and only then renames them all into place. If a temp
write fails, nothing was written. If a rename fails part way, the error
names the files already replaced.

Usage: catalogue.py [--check | --validate-plugins] [--json]
                    [--marketplace-name NAME --owner OWNER] <repo>
"""
import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

CAT_START, CAT_END = "<!-- catalogue:start -->", "<!-- catalogue:end -->"
META_START, META_END = "<!-- plugin-meta:start -->", "<!-- plugin-meta:end -->"
HEADER = ("| Plugin | Version | Skills | Commands | Description |",
          "|--------|---------|--------|----------|-------------|")
ROW_RE = re.compile(r"^\| \[([^\]]+)\]\(\./plugins/[^)]*\) \| ([^|]*) \| ([^|]*) \| ([^|]*) \| (.*) \|$")
INSTALL_RE = re.compile(r"/plugin (?:un)?install ([A-Za-z0-9_.-]+)@([A-Za-z0-9_.-]+)")
INSTALL_SCRIPT = "scripts/install-plugin.sh"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.+-]+)?$")
DEFAULT_MARKET_DESC = "Reusable Agent Skills and Plugins for Claude Code"


class CannotRun(Exception):
    def __init__(self, msg, written=()):
        super().__init__(msg)
        self.written = list(written)


def read(path, rel):
    """Read a text file as UTF-8 and keep its line endings as they are.

    Path.read_text() turns CRLF into LF, which would rewrite a CRLF file's
    every line on the next write, so this decodes the bytes instead.
    """
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise CannotRun(f"{rel}: {e}")


def guard(repo, path, rel):
    """Refuse a write target (or a plugin directory) that is a symlink or
    resolves outside the repo, so a write can never land outside it."""
    if path.is_symlink():
        raise CannotRun(f"{rel}: is a symlink; catalogue.py will not read or write through it")
    try:
        path.resolve().relative_to(repo)
    except ValueError:
        raise CannotRun(f"{rel}: is outside the repo (resolves to {path.resolve()})")


def write_all(writes):
    """writes: [(path, text, rel)]. All or nothing as far as the OS allows:
    every new text goes to a temp file in the target's own directory first,
    and only when all of them are written are they renamed into place."""
    temps = []
    try:
        for path, text, rel in writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".catalogue-")
            temps.append(tmp)
            # Bytes, not write_text(newline=""): that argument needs Python 3.10.
            with os.fdopen(fd, "wb") as fh:
                fh.write(text.encode("utf-8"))
            if path.exists():
                os.chmod(tmp, path.stat().st_mode & 0o7777)
            else:
                os.chmod(tmp, 0o644)
    except OSError as e:
        for t in temps:
            try:
                os.unlink(t)
            except OSError:
                pass
        raise CannotRun(f"{rel}: {e}; nothing was written")
    done = []
    for i, ((path, _, rel), tmp) in enumerate(zip(writes, temps)):
        try:
            os.replace(tmp, str(path))
        except OSError as e:
            for t in temps[i:]:
                try:
                    os.unlink(t)
                except OSError:
                    pass
            already = ", ".join(done) or "none"
            raise CannotRun(f"{rel}: {e}; already written: {already}", written=done)
        done.append(rel)
    return done


def standalone_plugins():
    f = Path(__file__).with_name("standalone-plugins.txt")
    lines = read(f, str(f)).splitlines()
    return {l.strip() for l in lines if l.strip() and not l.strip().startswith("#")}


def list_dir(d, rel):
    """The entries of directory d (none when it does not exist). An unreadable
    directory is CannotRun: glob() would skip it and count 0."""
    if not d.exists() and not d.is_symlink():
        return []
    try:
        if not d.is_dir():
            raise CannotRun(f"{rel}: is not a directory")
        with os.scandir(str(d)) as it:
            return sorted((e for e in it if not e.name.startswith(".")), key=lambda e: e.name)
    except OSError as e:
        raise CannotRun(f"{rel}: {e}")


def plugin_parts(d, rel):
    """(skills, agents, commands) of plugin directory d, read strictly."""
    skills = []
    for e in list_dir(d / "skills", f"{rel}/skills"):
        try:
            if e.is_dir() and stat.S_ISREG(os.stat(os.path.join(e.path, "SKILL.md")).st_mode):
                skills.append(e.name)
        except FileNotFoundError:
            continue
        except OSError as err:
            raise CannotRun(f"{rel}/skills/{e.name}: {err}")
    def md_files(sub):
        out = []
        for e in list_dir(d / sub, f"{rel}/{sub}"):
            try:
                if e.name.endswith(".md") and e.is_file():
                    out.append(e.name[:-3])
            except OSError as err:
                raise CannotRun(f"{rel}/{sub}/{e.name}: {err}")
        return out
    return skills, md_files("agents"), md_files("commands")


def plural(n, word):
    return f"**{n}** {word}{'' if n == 1 else 's'}"


def load_plugins(repo, skip):
    pdir = repo / "plugins"
    if not pdir.is_dir():
        raise CannotRun(f"{repo}: no plugins/ directory")
    plugins = []
    for d in sorted(p for p in pdir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if d.name in skip:
            continue
        guard(repo, d, f"plugins/{d.name}")
        mf = d / ".claude-plugin" / "plugin.json"
        rel = mf.relative_to(repo)
        if not mf.is_file():
            raise CannotRun(f"{rel}: missing")
        try:
            m = json.loads(read(mf, rel))
        except ValueError as e:
            raise CannotRun(f"{rel}: {e}")
        if not isinstance(m, dict):
            raise CannotRun(f"{rel}: not a JSON object")
        for k in ("name", "version", "description"):
            if not isinstance(m.get(k), str) or not m[k].strip():
                raise CannotRun(f"{rel}: '{k}' missing or empty")
        if m["name"] != d.name:
            raise CannotRun(f"{rel}: name {m['name']} does not match directory {d.name}")
        if not NAME_RE.match(m["name"]):
            raise CannotRun(f"{rel}: name {m['name']!r} is not lower-case letters, digits and hyphens")
        for k in ("name", "description"):
            if "<!--" in m[k] or "-->" in m[k]:
                raise CannotRun(f"{rel}: {k} contains an HTML comment marker (<!-- or -->); it would break the catalogue markers")
        if not VERSION_RE.match(m["version"]):
            raise CannotRun(f"{rel}: version {m['version']!r} is not X.Y.Z (with an optional -pre or +build part)")
        for k in ("version", "description"):
            if any(c in m[k] for c in "|\n\r"):
                raise CannotRun(f"{rel}: {k} contains '|' or a newline; it cannot sit in a table row")
            if m[k] != m[k].strip():
                raise CannotRun(f"{rel}: {k} has spaces before or after it; a table row cannot keep them")
        skills, agents, commands = plugin_parts(d, f"plugins/{d.name}")
        plugins.append({
            "name": m["name"], "version": m["version"], "description": m["description"],
            "skills": skills, "agents": agents, "commands": commands, "dir": d,
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
    """Drift lines for the README table block (all of them a write fixes)."""
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
    """Drift lines for marketplace.json's plugins[] (all of them a write fixes)."""
    out = []
    plist = current.get("plugins", [])
    have = {e.get("name"): e for e in plist if isinstance(e, dict)} if isinstance(plist, list) else {}
    want = {e["name"] for e in entries}
    for e in entries:
        h = have.get(e["name"])
        if h is None:
            out.append(f"marketplace.json: {e['name']}: missing")
            continue
        for k in ("source", "description", "version"):
            if h.get(k) != e[k]:
                out.append(f"marketplace.json: {e['name']}: {k} differs from plugin.json")
    for name in have:
        if name not in want:
            out.append(f"marketplace.json: {name}: no such plugin")
    return out


def install_drift(readme, names, market, repo, skip):
    """Drift a write cannot fix: install commands and the install script."""
    out = []
    for m in INSTALL_RE.finditer(readme):
        x, mk = m.group(1), m.group(2)
        if x in skip and mk == f"{x}-repo":
            continue
        if mk != market:
            out.append(f"README.md: {m.group(0)}: marketplace is {market}")
        if x != "PLUGIN_NAME" and x not in names:
            out.append(f"README.md: {m.group(0)}: no plugin {x}")
    if INSTALL_SCRIPT in readme and not (repo / INSTALL_SCRIPT).is_file():
        out.append(f"README.md: {INSTALL_SCRIPT}: does not exist")
    return out


def name_drift(p, text):
    """Drift a write cannot fix: a skill or agent the plugin README never names.

    A name counts only as inline code (`name`), as <plugin>:name or as /name.
    A plain word does not: a skill called "install" is not named by the
    words "/plugin install"."""
    out = []
    rel = f"plugins/{p['name']}/README.md"
    end = r"(?![A-Za-z0-9_-])"
    for kind, names in (("skill", p["skills"]), ("agent", p["agents"])):
        for n in names:
            e = re.escape(n)
            pat = (r"`" + e + r"`"
                   + r"|(?<![A-Za-z0-9_-])" + re.escape(p["name"]) + r":" + e + end
                   + r"|(?<![A-Za-z0-9_.:/-])/" + e + end)
            if not re.search(pat, text):
                out.append(f"{rel}: does not name {kind} {n}")
    return out


def insert_meta(text, p):
    """Put a meta block after the first '# ' heading (or at the top)."""
    nl = newline_of(text)
    lines = text.split(nl)
    at, fence = 0, None
    for i, l in enumerate(lines):
        fm = FENCE_RE.match(l)
        if fence is None and fm:
            fence = fm.group(1)
        elif fence is not None:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
        elif l.startswith("# "):
            at = i + 1
            break
    block = [META_START, meta(p), META_END]
    if at > 0:
        block = [""] + block
    if at < len(lines) and lines[at] != "":
        block = block + [""]
    lines[at:at] = block
    return nl.join(lines)


def load_checked(repo):
    """Load every plugin and check every write target; nothing is written."""
    skip = standalone_plugins()
    guard(repo, repo / "README.md", "README.md")
    guard(repo, repo / ".claude-plugin" / "marketplace.json", ".claude-plugin/marketplace.json")
    plugins = load_plugins(repo, skip)
    for p in plugins:
        guard(repo, p["dir"] / "README.md", f"plugins/{p['name']}/README.md")
    return skip, plugins


def run(repo, check, market_name, owner):
    """Return (written, drift). In write mode drift is only what a write cannot fix."""
    rp = repo / "README.md"
    mp = repo / ".claude-plugin" / "marketplace.json"
    # Every write target is checked before anything is read or written.
    skip, plugins = load_checked(repo)
    names = {p["name"] for p in plugins}
    fixable, manual = [], []

    # Root README
    readme = read(rp, "README.md")
    head, block, tail = split(readme, CAT_START, CAT_END, "README.md")
    new_readme = head + readme_block(plugins, newline_of(readme)) + tail
    rows = readme_drift(block, plugins)
    fixable += rows
    if new_readme != readme and not rows:
        fixable.append("README.md: catalogue table formatting differs from catalogue.py output")

    # Marketplace
    mp_text = None
    if mp.is_file():
        mp_text = read(mp, ".claude-plugin/marketplace.json")
        try:
            market = json.loads(mp_text)
        except ValueError as e:
            raise CannotRun(f".claude-plugin/marketplace.json: {e}")
        if not isinstance(market, dict) or not isinstance(market.get("name"), str) or not market["name"]:
            raise CannotRun(".claude-plugin/marketplace.json: no top-level name")
    elif mp.exists():
        raise CannotRun(".claude-plugin/marketplace.json: not a file")
    else:
        if not (market_name and owner):
            raise CannotRun(".claude-plugin/marketplace.json is missing; pass --marketplace-name and --owner")
        market = {"name": market_name, "owner": {"name": owner},
                  "metadata": {"description": DEFAULT_MARKET_DESC}, "plugins": []}
    entries = market_entries(plugins)
    new_market = dict(market)
    new_market["plugins"] = entries
    if mp_text is None:
        fixable.append("marketplace.json: missing")
    else:
        md = market_drift(market, entries)
        fixable += md
        if not md and mp_text != dump(new_market):
            fixable.append("marketplace.json: formatting differs from catalogue.py output")

    # Plugin READMEs
    plugin_writes = []
    for p in plugins:
        f = p["dir"] / "README.md"
        rel = f"plugins/{p['name']}/README.md"
        if not f.is_file():
            manual.append(f"{rel}: missing")
            continue
        text = read(f, rel)
        if META_START not in text and META_END not in text:
            fixable.append(f"{rel}: no meta line ({META_START} … {META_END})")
            new = insert_meta(text, p)
        else:
            h, b, t = split(text, META_START, META_END, rel)
            pnl = newline_of(text)
            if b != pnl + meta(p) + pnl:
                fixable.append(f"{rel}: meta line differs ({meta(p)})")
            new = h + pnl + meta(p) + pnl + t
        manual += name_drift(p, new)
        if new != text:
            plugin_writes.append((f, new, rel))

    manual += install_drift(new_readme, names, new_market["name"], repo, skip)

    writes = []
    if new_readme != readme:
        writes.append((rp, new_readme, "README.md"))
    if mp_text != dump(new_market):
        writes.append((mp, dump(new_market), ".claude-plugin/marketplace.json"))
    writes += plugin_writes

    if check:
        # --check must fail whenever a write would change a file. Every change
        # a write makes today is already named by a rule above; this is a net
        # so a future rule cannot leave a change unreported.
        drift = fixable + manual
        for _, _, rel in writes:
            key = "marketplace.json" if rel.endswith("marketplace.json") else rel
            if not any(d.startswith(key + ":") for d in drift):
                drift.append(f"{key}: differs from catalogue.py output")
        return [], drift

    return write_all(writes), manual


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Write or check a plugin monorepo's catalogue (README table, "
                    "marketplace.json, plugin README meta lines) from each plugin.json.",
        epilog="Exit: 0 clean or written, 1 drift, 2 cannot run.")
    ap.add_argument("repo", type=Path, help="the monorepo root")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="write nothing; report every difference")
    mode.add_argument("--validate-plugins", action="store_true",
                      help="write nothing; only load and check every plugin and write target (exit 0 or 2)")
    ap.add_argument("--json", action="store_true", help='print {"written", "drift", "errors"} as JSON')
    ap.add_argument("--marketplace-name", help="marketplace name, used only when marketplace.json is missing")
    ap.add_argument("--owner", help="marketplace owner, used only when marketplace.json is missing")
    a = ap.parse_args(argv)
    written, drift, errors = [], [], []
    try:
        if a.validate_plugins:
            load_checked(a.repo.resolve())
        else:
            written, drift = run(a.repo.resolve(), a.check, a.marketplace_name, a.owner)
    except CannotRun as e:
        errors = [str(e)]
        written = e.written
    except Exception as e:  # fail closed: an unexpected error is "cannot run", never "drift"
        errors = [f"{type(e).__name__}: {e}"]
    if a.json:
        print(json.dumps({"written": written, "drift": drift, "errors": errors}, indent=2, ensure_ascii=False))
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
