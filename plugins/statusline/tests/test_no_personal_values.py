"""No file in the plugin carries the author's own values (#158).

The forbidden tokens are stored as SHA-256 hashes so this file does not carry them either:
the author's first name, last name, GitHub login, and the one repo name the old
context-bar.sh hardcoded. Tokens are runs of letters, digits, '-', '.' and '_', split again
on '.' and '_'; every run of consecutive '-'-separated parts is lowercased and hashed.
To check a candidate token: printf '%s' TOKEN | shasum -a 256
"""
import hashlib
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
FORBIDDEN = {
    "42b5bf6a3fa51849bc05c7050141a81591133b5f470cdef4ff6628e1222ff0a1",
    "3268eeadb560d946d44fbe0ab8126795a0acd406e88a96261f9a930fbdc804d5",
    "a10e2ddcdd045e655657ccf01e5bf55b6bb4b786cc2f7208a0469ceb7333fd6e",
    "cf8ecb2554470e7885282f67c586b27f1df77fd7dbc9cb520a4ed2da2d647f4d",
}
TOKEN = re.compile(r"[A-Za-z0-9._-]+")
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
# The MIT licence must name its copyright holder.
SKIP_FILES = {Path("LICENSE")}


def _h(token: str) -> str:
    return hashlib.sha256(token.lower().encode()).hexdigest()


def candidates(token: str):
    for chunk in re.split(r"[._]+", token):
        parts = [p for p in chunk.split("-") if p]
        for i in range(len(parts)):
            for j in range(i + 1, len(parts) + 1):
                yield "-".join(parts[i:j])


def hits_in(text: str, forbidden: set) -> list:
    return [i for i, line in enumerate(text.splitlines(), 1)
            if any(_h(c) in forbidden for t in TOKEN.findall(line) for c in candidates(t))]


def test_the_scan_catches_a_planted_token():
    planted = {_h("someone")}
    for line in ("/Users/someone/dev", "-Users-someone-dev-x", "someone_dev", "x.someone.y"):
        assert hits_in(line, planted) == [1], line
    assert hits_in("someoneelse", planted) == []


def test_no_personal_values_in_the_plugin():
    bad = []
    for p in sorted(PLUGIN.rglob("*")):
        rel = p.relative_to(PLUGIN)
        if p.is_file() and not SKIP_PARTS & set(rel.parts) and rel not in SKIP_FILES:
            bad += [f"{rel}:{i}" for i in hits_in(p.read_text(errors="replace"), FORBIDDEN)]
            bad += [str(rel)] if hits_in(str(rel), FORBIDDEN) else []
    assert bad == [], "personal values found; genericize them:\n" + "\n".join(bad)
