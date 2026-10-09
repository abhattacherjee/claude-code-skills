#!/usr/bin/env python3
"""secret_scan.py — check files for secrets before they are sent to a model.

Usage: secret_scan.py FILE [FILE ...]

Scans each file for the secret formats in audit_record.SECRET_PATTERNS (the same
list redact() uses), and scans unified-diff headers for files whose names look
like secrets (SECRET_NAME_GLOBS, the same list as detect-mode.sh). Prints one
line per hit and never the matched value:

  <path>:<line> <pattern-name>                 an added or context line, new-file line
  <path>:<line> <pattern-name> (removed line)  a removed line, old-file line
  <path>:0 secret-file-name                    the diff adds, changes or deletes that file
  <input-file>:<line> <pattern-name>           text that is not inside a diff
  <input-file> (JSON-decoded):<n> <pattern-name>
                                               the n-th string in a JSON file, after
                                               its escapes are decoded (a reader sees
                                               "\u0041KIA..." as "AKIA...")

Exit codes:
  0  no hits
  2  usage error, or an input file cannot be read (never treated as clean)
  4  one or more hits
"""
import ast
import bisect
import fnmatch
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_record import SECRET_PATTERNS  # noqa: E402

EXIT_CLEAN, EXIT_USAGE, EXIT_HIT = 0, 2, 4
# Must match SECRET_NAME_GLOBS in detect-mode.sh; test_secret_scan.py checks that.
# Matched against the lower-cased last part of the path.
SECRET_NAME_GLOBS = ('.env', '.env.*', '*.env', '.envrc', '*.pem', '*.key', 'id_rsa*', 'id_ed25519*',
                     'id_ecdsa*', 'id_dsa*', '*credentials*', '*.p12', '*.pfx', '.netrc', '.npmrc',
                     '.pypirc', '.pgpass')
# Scan only, never redact: a value assigned to a secret-sounding name. A quoted
# literal after password/secret/api_key/token, or an upper-case env line such as
# DB_PASSWORD=... . Values with placeholder words are skipped. Measured on this
# repo: no hit on the whole develop history as one diff (5.7 MB) nor on its six
# largest commits.
ASSIGNMENT_RULES = (
    re.compile(r"""(?i)(?:password|passwd|pwd|secret|api_?key|access_?key|auth_?token|token)["']?\s*[:=]\s*["']([^"'\s]{8,})["']"""),
    re.compile(r"""(?m)^[+ -]?\s*(?:export\s+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_?KEY|ACCESS_?KEY|TOKEN)[A-Z0-9_]*\s*=\s*([A-Za-z0-9_+/=.:@!#%^&*~-]{8,})\s*$"""),
)
PLACEHOLDER_RE = re.compile(r"(?i)x{4,}|\*{3,}|\.{3}|changeme|example|placeholder|your[_-]|^<|\$\{|\{\{|"
                            r"redacted|dummy|fake|stub|test|canary|sample|mock")
# What `git diff` writes when the user's config turns color on. Stripped before
# parsing, so a colored header still names its file.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def find_secrets(text):
    """(start offset, pattern name) for every secret in text: SECRET_PATTERNS, then
    the scan-only assignment rules."""
    found = []
    for name, rx in SECRET_PATTERNS:
        found += [(m.start(), name) for m in rx.finditer(text)]
    for rx in ASSIGNMENT_RULES:
        found += [(m.start(), "secret-assignment") for m in rx.finditer(text)
                  if not PLACEHOLDER_RE.search(m.group(1))]
    return found


def show(path):
    """A path from the untrusted diff, safe to print on one line: control and other
    non-printable characters are written as escapes, so a newline cannot forge a hit."""
    return path if path.isprintable() else path.encode("unicode_escape").decode("ascii")
HIT_NAME_RE = re.compile(r":\d+ (\S+)(?: \(removed line\))?$")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
QUOTED_HEADER_RE = re.compile(r'^("(?:[^"\\]|\\.)*"|\S+) ("(?:[^"\\]|\\.)*"|\S+)$')


def unquote(path):
    """A path as git prints it: maybe C-quoted, maybe with an a/ or b/ prefix, and on
    ---/+++ lines maybe a tab after it (git adds one when the name has a space).
    Returns None for /dev/null."""
    if not path.startswith('"'):
        path = path.split("\t", 1)[0]
    if path.startswith('"') and path.endswith('"'):
        try:
            path = ast.literal_eval("b" + path).decode("utf-8", "replace")
        except (ValueError, SyntaxError):
            path = path[1:-1]
    if path == "/dev/null":
        return None
    if path[:2] in ("a/", "b/"):
        path = path[2:]
    return path


def header_paths(rest):
    """(old, new) from the text after "diff --git ". git quotes a path with special
    characters but not one with spaces, so "a/x y b/x y" is split where both halves
    match, else at the last " b/"."""
    if rest.startswith('"'):
        m = QUOTED_HEADER_RE.match(rest)
        return (unquote(m.group(1)), unquote(m.group(2))) if m else (None, None)
    cuts = [i for i in range(len(rest)) if rest.startswith(" b/", i)]
    for i in cuts:
        if rest[2:i] == rest[i + 3:]:
            return unquote(rest[:i]), unquote(rest[i + 1:])
    if cuts:
        return unquote(rest[:cuts[-1]]), unquote(rest[cuts[-1] + 1:])
    return None, None


def is_secret_name(path):
    name = path.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(name, glob) for glob in SECRET_NAME_GLOBS)


def map_lines(lines):
    """For each physical line, (path, line, removed): where that line sits in the
    files the diff describes. path is None for text outside any diff; line is 0 for a
    diff header line. Also returns every path the diff names, and each file's
    new-side path (None when the diff deletes it). Hunk ends come from the hunk
    header counts, so a removed "-- x" (shown as "--- x") stays in its hunk."""
    out, paths, new_sides = [], [], []
    old_path = new_path = None
    old_left = new_left = 0
    old_no = new_no = 0
    in_file = False
    for raw in lines:
        if old_left > 0 or new_left > 0:
            tag = raw[:1]
            if tag == "-" and old_left > 0:
                out.append((old_path or new_path, old_no, True))
                old_no += 1
                old_left -= 1
                continue
            if tag == "+" and new_left > 0:
                out.append((new_path or old_path, new_no, False))
                new_no += 1
                new_left -= 1
                continue
            if tag == " " or (raw == "" and old_left > 0 and new_left > 0):
                out.append((new_path or old_path, new_no, False))
                old_no += 1
                new_no += 1
                old_left -= 1
                new_left -= 1
                continue
            if tag == "\\":
                out.append((new_path or old_path, 0, False))
                continue
            old_left = new_left = 0  # a malformed hunk: fall through to header parsing
        if raw.startswith("diff --git "):
            in_file = True
            old_path, new_path = header_paths(raw[len("diff --git "):])
            paths += [p for p in (old_path, new_path) if p]
            new_sides.append(new_path)
            out.append((new_path or old_path, 0, False))
            continue
        hunk = HUNK_RE.match(raw) if in_file else None
        if hunk:
            old_no, new_no = int(hunk.group(1)), int(hunk.group(3))
            old_left = int(hunk.group(2)) if hunk.group(2) is not None else 1
            new_left = int(hunk.group(4)) if hunk.group(4) is not None else 1
            out.append((new_path or old_path, 0, False))
            continue
        if in_file:
            for prefix, which in (("--- ", "old"), ("+++ ", "new"), ("rename from ", "old"),
                                  ("rename to ", "new"), ("copy from ", "old"), ("copy to ", "new")):
                if raw.startswith(prefix):
                    value = raw[len(prefix):]
                    if prefix in ("--- ", "+++ "):
                        value = unquote(value)
                    elif value.startswith('"'):
                        value = unquote(value)
                    if which == "new" and new_sides:
                        new_sides[-1] = value
                    if value:
                        paths.append(value)
                        if which == "old":
                            old_path = value
                        else:
                            new_path = value
                    break
            out.append((new_path or old_path, 0, False))
            continue
        out.append((None, None, False))
    return out, paths, new_sides


def hunk_lines(text):
    """{path: set of new-file line numbers} that the diff's hunks show (added or
    context lines)."""
    lines = ANSI_RE.sub("", text).split("\n")
    out = {}
    for path, line, removed in map_lines(lines)[0]:
        if path and line and not removed:
            out.setdefault(path, set()).add(line)
    return out


def new_side_paths(text):
    """The files a diff leaves in place: each file's new-side path, deleted ones left out."""
    return {p for p in map_lines(ANSI_RE.sub("", text).split("\n"))[2] if p}


def scan_text(text, label):
    """Hits as output lines, in order, without the matched values."""
    text = ANSI_RE.sub("", text)
    lines = text.split("\n")
    where, paths, _ = map_lines(lines)
    starts, pos = [], 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1
    hits, seen = [], set()
    for path in paths:
        if is_secret_name(path) and path not in seen:
            seen.add(path)
            hits.append("%s:0 secret-file-name" % show(path))
    found = [(bisect.bisect_right(starts, pos) - 1, name) for pos, name in find_secrets(text)]
    for idx, name in sorted(set(found)):
        path, line, removed = where[idx]
        if path is None:
            hits.append("%s:%d %s" % (show(label), idx + 1, name))
        else:
            hits.append("%s:%d %s%s" % (show(path), line, name, " (removed line)" if removed else ""))
    return hits


def _unique_keys(pairs):
    """object_pairs_hook: json.loads keeps only the last of two equal keys, so a
    value in the first would be sent (in the raw file) but never checked. The key
    is not named in the error, since it is untrusted text."""
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("an object has a duplicate key")
    return dict(pairs)


def _no_constant(name):
    raise ValueError("%s is not JSON" % name)


def _finite_float(text):
    value = float(text)
    if value in (float("inf"), float("-inf")):
        raise ValueError("a number is out of range")
    return value


def load_strict_json(text):
    """Parse text as strict JSON: no duplicate keys, no NaN or Infinity (written or
    by overflow). Raises ValueError otherwise. The review scripts parse --findings
    and --prior with this, refuse what it rejects, and send dump_json(value)."""
    return json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_no_constant,
                      parse_float=_finite_float)


def dump_json(value):
    """The text the review scripts send for a parsed JSON input. ensure_ascii=False
    leaves no \\u escapes, so a scan of this text sees every string as a reader does."""
    return json.dumps(value, indent=1, ensure_ascii=False)


def json_strings(text):
    """Every key and string value in text, decoded, if text is strict JSON; else None."""
    try:
        data = load_strict_json(text)
    except ValueError:
        return None
    out, stack = [], [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for key, value in item.items():
                out.append(key)
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return out


def scan_strings(strings, label):
    """Hits in each string on its own, numbered from 1, so a key cannot be split
    across two strings and a hit names the string it came from."""
    hits = []
    for n, value in enumerate(strings, 1):
        for name in sorted({name for _, name in find_secrets(value)}):
            hits.append("%s:%d %s" % (show(label), n, name))
    return hits


def scan_file(path):
    """Hit lines for one file: its text as read, and for a JSON file each decoded
    string too, since the review scripts and the models decode JSON escapes.
    Raises OSError if it cannot be read."""
    with open(path, "rb") as fh:
        data = fh.read()
    text = data.decode("utf-8", "replace")
    hits = scan_text(text, path)
    strings = json_strings(text)
    if strings is not None:
        # Report only what the escapes hid: per pattern, the decoded hits beyond
        # the ones the raw text already showed.
        seen = {}
        for hit in hits:
            name = HIT_NAME_RE.search(hit).group(1)
            seen[name] = seen.get(name, 0) + 1
        for hit in scan_strings(strings, "%s (JSON-decoded)" % path):
            name = hit.rsplit(" ", 1)[1]
            if seen.get(name, 0) > 0:
                seen[name] -= 1
            else:
                hits.append(hit)
    return hits


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] in (["-h"], ["--help"]):
        print(__doc__.strip())
        return EXIT_CLEAN
    if not args:
        print("secret_scan: give one or more files to scan (see --help)", file=sys.stderr)
        return EXIT_USAGE
    hits = []
    for path in args:
        try:
            hits += scan_file(path)
        except OSError as exc:
            print("secret_scan: cannot read %s: %s" % (path, exc.strerror or exc), file=sys.stderr)
            return EXIT_USAGE
    for hit in hits:
        print(hit)
    return EXIT_HIT if hits else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
