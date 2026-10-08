"""Regexes that gh runs must be RE2 (#204).

`gh api --jq` runs gojq, whose regexes are Go's regexp package (RE2): no look-around and no
backreferences. The tests stub gh with native jq (Oniguruma), which accepts both, so a
lookbehind passed every test while real gh failed every discovery query with
`invalid named capture`. These checks close that gap: a text scan of every script that
uses --jq, and a compile of find-promotable's real filter with Go's regexp when Go is here.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from gbtest import PLUGIN, SKILLS_DIR

FIND = SKILLS_DIR / "promote-shipped" / "scripts" / "find-promotable.sh"
RECONCILE = SKILLS_DIR / "plan-milestones" / "scripts" / "release-reconcile.sh"
LOOKAROUND = ("(?<", "(?=", "(?!")
# A jq regex function call; its line is checked for a backreference (\\1 in a jq string).
REGEX_CALL = re.compile(r"\b(test|match|capture|scan|splits?|sub|gsub)\(")
BACKREF = re.compile(r"\\\\[1-9]")
KEYWORD = "(?i)(^|[^A-Za-z0-9_])(close[sd]?|fix(e[sd])?|resolve[sd]?):?"


def jq_scripts():
    return sorted(p for p in PLUGIN.rglob("*.sh") if "tests" not in p.parts
                  and "--jq" in p.read_text())


def scan(text):
    """(line number, problem) for every look-around, and every backreference on a line that
    calls a jq regex function."""
    bad = []
    for i, line in enumerate(text.splitlines(), 1):
        for token in LOOKAROUND:
            if token in line:
                bad.append((i, f"look-around {token}"))
        if REGEX_CALL.search(line) and BACKREF.search(line):
            bad.append((i, "backreference"))
    return bad


def test_the_scan_covers_the_find_promotable_filter():
    assert FIND in jq_scripts()
    lines = [ln for ln in FIND.read_text().splitlines() if REGEX_CALL.search(ln)]
    assert any("close[sd]?" in ln for ln in lines), "the keyword filter is not on a scanned line"


def test_the_scan_catches_a_planted_lookbehind_and_backreference():
    assert scan('x | test("(?i)(?<![a-z])closes") | y') == [(1, "look-around (?<")]
    assert scan('x | test("(a)\\\\1")') == [(1, "backreference")]
    assert scan('x | test("(?i)(^|[^A-Za-z0-9_])closes")') == []


@pytest.mark.parametrize("script", jq_scripts(), ids=lambda p: p.name)
def test_no_script_that_uses_gh_jq_has_regex_gh_cannot_run(script):
    assert scan(script.read_text()) == [], f"{script.name}: RE2 (gh --jq) cannot run this"


def test_find_promotable_and_release_reconcile_share_the_keyword_rule():
    # Same rule in both places: find-promotable tests one number, reconcile captures it.
    assert KEYWORD in FIND.read_text()
    assert KEYWORD in RECONCILE.read_text()


# The real filter, captured from a run, compiled with Go's regexp: what gh actually does.
_STUB = r'''#!/usr/bin/env bash
jqf=""; prev=""
for a in "$@"; do [ "$prev" = "--jq" ] && jqf="$a"; prev="$a"; done
case "$1 $2" in
  "api graphql") printf '%s\n' "$jqf" >> "$FILTERS"; echo '[]'; exit 0 ;;
esac
exit 1
'''

_GO = r'''package main

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
)

func main() {
	s := bufio.NewScanner(os.Stdin)
	s.Buffer(make([]byte, 1<<20), 1<<20)
	bad := 0
	for s.Scan() {
		if _, err := regexp.Compile(s.Text()); err != nil {
			fmt.Println(err)
			bad = 1
		}
	}
	os.Exit(bad)
}
'''


def _inventory():
    return {
        "project": {"id": "PVT_1", "title": "Board", "number": 1},
        "statusField": {"id": "F", "name": "Status",
                        "options": [{"id": "o1", "name": "Dev Complete"}, {"id": "o2", "name": "Done"}],
                        "doneOptionId": "o2", "doneOptionName": "Done"},
        "items": [{"itemId": "I1", "status": "Dev Complete", "statusOptionId": "o1",
                   "contentType": "Issue",
                   "issue": {"number": 42, "title": "t", "state": "CLOSED", "stateReason": "COMPLETED",
                             "url": "https://github.com/o.x/r/issues/42", "repo": "o.x/r",
                             "linkedPRs": []},
                   "pullRequest": None, "draftTitle": None}],
    }


def go_compile(tmp_path, patterns):
    prog = tmp_path / "re2check.go"
    prog.write_text(_GO)
    env = dict(os.environ, GOCACHE=str(tmp_path / "gocache"), GOFLAGS="", GOTOOLCHAIN="local")
    return subprocess.run(["go", "run", str(prog)], input="\n".join(patterns) + "\n",
                          capture_output=True, text=True, env=env, timeout=300)


@pytest.mark.skipif(shutil.which("go") is None or shutil.which("jq") is None,
                    reason="needs go (for Go's regexp, which gh's gojq uses) and jq")
def test_find_promotables_real_filter_compiles_as_re2(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(_STUB)
    (bindir / "gh").chmod(0o755)
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps(_inventory()))
    filters = tmp_path / "filters.txt"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FILTERS=str(filters))
    done = subprocess.run(["bash", str(FIND), str(inv)], capture_output=True, text=True,
                          env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    text = filters.read_text()
    literals = re.findall(r'\b(?:test|match|capture)\("((?:[^"\\]|\\.)*)"', text)
    patterns = [json.loads(f'"{lit}"') for lit in literals]
    assert any("close[sd]?" in p and r"o\.x/r" in p for p in patterns), patterns
    r = go_compile(tmp_path, patterns)
    assert r.returncode == 0, f"Go's regexp (gh --jq) rejects: {r.stdout}{r.stderr}"


@pytest.mark.skipif(shutil.which("go") is None, reason="needs go")
def test_the_go_check_rejects_a_lookbehind(tmp_path):
    # The instrument works: the old pattern is the error real gh printed.
    r = go_compile(tmp_path, ["(?i)(?<![A-Za-z0-9_])closes"])
    assert r.returncode == 1 and "invalid" in r.stdout
