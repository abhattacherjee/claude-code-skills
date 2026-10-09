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

Exit codes:
  0  no hits
  2  usage error, or an input file cannot be read (never treated as clean)
  4  one or more hits
"""
import ast
import bisect
import fnmatch
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_record import SECRET_PATTERNS  # noqa: E402

EXIT_CLEAN, EXIT_USAGE, EXIT_HIT = 0, 2, 4
# Must match SECRET_NAME_GLOBS in detect-mode.sh; test_secret_scan.py checks that.
# Matched against the lower-cased last part of the path.
SECRET_NAME_GLOBS = ('.env', '.env.*', '*.pem', '*.key', 'id_rsa*', 'id_ed25519*', '*credentials*',
                     '*.p12', '*.pfx')
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
GIT_HEADER_RE = re.compile(r'^diff --git ("(?:[^"\\]|\\.)*"|\S+) ("(?:[^"\\]|\\.)*"|\S+)$')


def unquote(path):
    """A path as git prints it: maybe C-quoted, maybe with an a/ or b/ prefix.
    Returns None for /dev/null."""
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


def is_secret_name(path):
    name = path.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(name, glob) for glob in SECRET_NAME_GLOBS)


def map_lines(lines):
    """For each physical line, (path, line, removed): where that line sits in the
    files the diff describes. path is None for text outside any diff; line is 0 for a
    diff header line. Also returns every path the diff names. Hunk ends come from the
    hunk header counts, so a removed "-- x" (shown as "--- x") stays in its hunk."""
    out, paths = [], []
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
        header = GIT_HEADER_RE.match(raw)
        if header:
            in_file = True
            old_path, new_path = unquote(header.group(1)), unquote(header.group(2))
            paths += [p for p in (old_path, new_path) if p]
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
    return out, paths


def scan_text(text, label):
    """Hits as output lines, in order, without the matched values."""
    lines = text.split("\n")
    where, paths = map_lines(lines)
    starts, pos = [], 0
    for line in lines:
        starts.append(pos)
        pos += len(line) + 1
    hits, seen = [], set()
    for path in paths:
        if is_secret_name(path) and path not in seen:
            seen.add(path)
            hits.append("%s:0 secret-file-name" % path)
    found = []
    for name, rx in SECRET_PATTERNS:
        for m in rx.finditer(text):
            found.append((bisect.bisect_right(starts, m.start()) - 1, name))
    for idx, name in sorted(found):
        path, line, removed = where[idx]
        if path is None:
            hits.append("%s:%d %s" % (label, idx + 1, name))
        else:
            hits.append("%s:%d %s%s" % (path, line, name, " (removed line)" if removed else ""))
    return hits


def scan_file(path):
    """Hit lines for one file. Raises OSError if it cannot be read."""
    with open(path, "rb") as fh:
        data = fh.read()
    return scan_text(data.decode("utf-8", "replace"), path)


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
