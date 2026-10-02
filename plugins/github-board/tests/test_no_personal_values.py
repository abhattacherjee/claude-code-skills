"""No file in the plugin carries the author's own values (#146).

The forbidden tokens are stored as SHA-256 hashes so this file does not carry them either:
the author's GitHub login and every repo name in the pre-#146 FROZEN, ALWAYS, TOOLING and
SEASON constants of weekly-focus.py (19 tokens; one of them, git-flow, is allowed as a
generic word, see GENERIC). Text is split into tokens on anything but
letters, digits and '-', lowercased, and hashed. `com.<login>.weekly-focus-sync` splits into
com / <login> / weekly-focus-sync, so the login hash catches the old launchd label too.
To check a candidate token: printf '%s' TOKEN | shasum -a 256
"""
import hashlib
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
FORBIDDEN = {
    "3268eeadb560d946d44fbe0ab8126795a0acd406e88a96261f9a930fbdc804d5",
    "cf8ecb2554470e7885282f67c586b27f1df77fd7dbc9cb520a4ed2da2d647f4d",
    "42ef2bf0562d528872334ccc1fe7b8fb5cec1628cd0955c2ebbd64349a57d3e2",
    "2b3d3623a09ba50b31a21db0aa31cb428d0c349a1c48b7df06b665c383d9905b",
    "375c078cd4b9b56abbaa02662a6a61b995d3651313e2336ff9aff3358d38ed3a",
    "ca272ae82d4c3c15b2ebab0ffb3b84a655224e1dc6bd27dd92a600c39db87608",
    "b0019ef18d89eaa86c7cebe680bc5cd820d4cd2a5ac233006c09b0ba7415b89b",
    "c49fac153a2d8a398dd22a32f67d816b1b1b4a8d9d4bae31d45d51ed50950612",
    "60b1037df992cde7cfa185303c86ff57c9d4067bfbf91e3b1f03b77a9fc94e20",
    "2efb9a597ae3c6ddc0e42a1082adae0893afcea4fbea91614f2fc51591904f69",
    "c00b8ce02147ec5f4536f565b41aab684a9a19865e07b3f922a0c90958b83350",
    "d652a40d10ca6e006b99e14e87addbded972f9d9b682c2b6959f97fc251b5af9",
    "01d1abd1891e9a89a193bdf7480b6bc65f81ef504e4c7569830ecc26184279d7",
    "ce64ec554e787e4ed335d742b30ff91e34786487043a9c21f94f15beddad4f31",
    "f955878785dd3ad4c856503c237567f02958a93a0b2225689194b0bf4e72b86a",
    "d5a28a15bc08bd019e4cca2a597e98384d6eecf3fc2f06dc3865c4afed8b1bff",
    "5829e8b56eca724d0378c75a2c04f31b31e52c0bf431ef720b5ed1bf90f08e6c",
    "b10f516ccef95b68f9c8b037d64592b437224873f2d6db81b2287e25fb2b8cb8",
    "a8b08ea6b01909f459c2d9e4d7381a046887894e83acd64dfa7c18077c42ae90",
}
# The plugin's root README.md may name the marketplace repo and the four repos whose callers
# move in follow-up PRs (the migration runbook). Nothing else may.
README_ALLOWED = {
    "01d1abd1891e9a89a193bdf7480b6bc65f81ef504e4c7569830ecc26184279d7",
    "c00b8ce02147ec5f4536f565b41aab684a9a19865e07b3f922a0c90958b83350",
    "d5a28a15bc08bd019e4cca2a597e98384d6eecf3fc2f06dc3865c4afed8b1bff",
    "d652a40d10ca6e006b99e14e87addbded972f9d9b682c2b6959f97fc251b5af9",
    "5829e8b56eca724d0378c75a2c04f31b31e52c0bf431ef720b5ed1bf90f08e6c",
}
# "Git-Flow" is also the name of the branching model, which the skills discuss by name
# ("Git-Flow develop merges"). The token cannot tell the model from the repo, so it is allowed
# everywhere; the other 18 tokens have no generic meaning.
GENERIC = {
    "d5a28a15bc08bd019e4cca2a597e98384d6eecf3fc2f06dc3865c4afed8b1bff",
}
TOKEN = re.compile(r"[A-Za-z0-9-]+")
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def _h(token: str) -> str:
    return hashlib.sha256(token.lower().encode()).hexdigest()


def hits_in(text: str, forbidden: set, allowed: set = frozenset()) -> list:
    """Line numbers (1-based) of lines carrying a forbidden, non-allowed token."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if any(_h(t) in forbidden and _h(t) not in allowed for t in TOKEN.findall(line)):
            out.append(i)
    return out


def _files():
    for p in sorted(PLUGIN.rglob("*")):
        rel = p.relative_to(PLUGIN)
        if p.is_file() and not SKIP_PARTS & set(rel.parts) and p.name != "CHANGELOG.md":
            yield p, rel


def test_hash_lists_are_well_formed():
    assert len(FORBIDDEN) == 19 and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in FORBIDDEN)
    assert README_ALLOWED <= FORBIDDEN and len(README_ALLOWED) == 5
    assert GENERIC <= FORBIDDEN and len(GENERIC) == 1


def test_the_scan_catches_a_planted_token_and_respects_the_allow_list():
    planted = {_h("planted-value")}
    assert hits_in("a\nx planted-value y\n", planted) == [2]
    assert hits_in("x Planted-Value.git\n", planted) == [1]
    assert hits_in("x planted-value-longer\n", planted) == []
    assert hits_in("x planted-value\n", planted, planted) == []


def test_no_personal_values_in_file_contents():
    bad = []
    for p, rel in _files():
        allowed = (README_ALLOWED if rel == Path("README.md") else set()) | GENERIC
        bad += [f"{rel}:{i}" for i in hits_in(p.read_text(errors="replace"), FORBIDDEN, allowed)]
    assert bad == [], "personal values found; genericize them:\n" + "\n".join(bad)


def test_no_personal_values_in_file_names():
    assert [str(rel) for _, rel in _files() if hits_in(str(rel), FORBIDDEN, GENERIC)] == []
