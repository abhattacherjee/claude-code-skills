"""context-bar.sh finds the current session's transcript from the working directory (#158).

Claude Code names ~/.claude/projects/<slug> by replacing every character that is not an
ASCII letter or digit with '-', counted in UTF-16 code units (JavaScript's
path.replace(/[^a-zA-Z0-9]/g, "-")), so '/', '.', '_', ' ' all become '-', 'é' becomes one
'-' and an emoji two. A slug longer than 200 characters is cut to 200 and gets
'-<hash>' appended. (Read from the Claude Code 2.1.x binary, and matches the names under
~/.claude/projects: '/.' gives '--', '_' gives '-'.)
"""
import os

import pytest

from sltest import CONTEXT_BAR

FULL = "█"


def _setup(env, workdir, slug, files=(("s1.jsonl", 400_000),), config=None):
    workdir.mkdir(parents=True, exist_ok=True)
    proj = (config or env.claude) / "projects" / slug
    proj.mkdir(parents=True)
    for i, (name, size) in enumerate(files):
        p = proj / name
        p.write_bytes(b"x" * size)
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))   # later files are newer
    return proj


def _run(env, bash, cwd, extra=None, args=()):
    return env.run(bash, CONTEXT_BAR, *args, cwd=cwd, extra=dict({"PWD": str(cwd)}, **(extra or {})))


def _slug(path):
    return "".join(c if (c.isascii() and c.isalnum()) else "-" * (len(c.encode("utf-16-le")) // 2)
                   for c in str(path))


@pytest.mark.parametrize("path,expected", [
    ("/Users/x/dev/a.b c", "-Users-x-dev-a-b-c"),
    ("/Users/x/.claude/obsidian-brain", "-Users-x--claude-obsidian-brain"),
    ("/Users/x/dev/claude_workspace", "-Users-x-dev-claude-workspace"),
    ("/private/tmp/claude-501/-Users-x", "-private-tmp-claude-501--Users-x"),
    ("/a/é", "-a--"),
    ("/a/😀", "-a---"),
])
def test_the_rule_this_file_encodes(path, expected):
    assert _slug(path) == expected


@pytest.mark.parametrize("name", ["a.b c", "my_proj", "v1.2 (copy)", "café", "emoji😀dir"])
def test_finds_the_project_dir_for_awkward_names(env, bash, name):
    work = env.tmp / "dev" / name
    _setup(env, work, _slug(work))
    r = _run(env, bash, work)
    assert r.returncode == 0, r.stderr
    assert FULL in r.stdout and "10%" in r.stdout


def test_bar_numbers(env, bash):
    work = env.tmp / "w"
    _setup(env, work, _slug(work), files=(("s.jsonl", 400_000),))
    r = _run(env, bash, work)
    # 400_000 / 8 + 50_000 = 100_000 tokens of 1_000_000 = 10%
    assert "10%" in r.stdout and "~100K/1000K tokens" in r.stdout


@pytest.mark.parametrize("size,color", [(400_000, "\033[32m"), (5_680_000, "\033[33m"),
                                         (6_440_000, "\033[31m")])
def test_colors_match_the_docs_green_amber_red_at_50_and_80(env, bash, size, color):
    # 5_680_000 B -> 760K tokens = 76% (amber, not red); 6_440_000 B -> 855K = 85% (red)
    work = env.tmp / "w"
    _setup(env, work, _slug(work), files=(("s.jsonl", size),))
    r = _run(env, bash, work)
    assert r.returncode == 0 and r.stdout.startswith(color), repr(r.stdout)


def _cc_hash(path) -> str:
    """Claude Code's suffix for a slug over 200 characters: Math.abs of a Java-style
    32-bit string hash over UTF-16 code units, in base 36 (read from the 2.1.x binary)."""
    h = 0
    data = str(path).encode("utf-16-le", "surrogatepass")
    for i in range(0, len(data), 2):
        h = (h * 31 + int.from_bytes(data[i:i + 2], "little")) & 0xFFFFFFFF
    h = abs(h - (1 << 32) if h >= 1 << 31 else h)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        h, r = divmod(h, 36)
        out = digits[r] + out
        if h == 0:
            return out


def test_cc_hash_known_values():
    # Values of Math.abs(Nee(s)).toString(36), computed with node from the function in the
    # Claude Code binary: function Nee(t){let e=0;for(...)e=(e<<5)-e+t.charCodeAt(n)|0;return e}
    assert _cc_hash("") == "0"
    assert _cc_hash("a") == "2p"
    assert _cc_hash("ab") == "2e9"
    assert _cc_hash("/private/var/x/café/😀/" + "d" * 60) == "a835co"


LONG = ("d" * 60, "e" * 60, "f" * 60, "g" * 60)


def test_long_path_matches_the_exact_hashed_dir(env, bash):
    work = env.tmp.joinpath(*LONG)
    slug = _slug(work)
    assert len(slug) > 200
    _setup(env, work, slug[:200] + "-" + _cc_hash(work), files=(("s.jsonl", 400_000),))
    r = _run(env, bash, work)
    assert r.returncode == 0, r.stderr
    assert "10%" in r.stdout


def test_long_path_never_reads_another_project_sharing_the_prefix(env, bash):
    # Two projects whose slugs share the first 200 characters: only the exact hash counts.
    work = env.tmp.joinpath(*LONG)
    slug = _slug(work)
    _setup(env, work, slug[:200] + "-" + _cc_hash(work), files=(("mine.jsonl", 400_000),))
    _setup(env, work, slug[:200] + "-000other", files=(("other.jsonl", 2_800_000),))
    r = _run(env, bash, work)
    assert r.returncode == 0 and "10%" in r.stdout, r.stdout


def test_long_path_with_only_a_foreign_prefix_match_exits_1(env, bash):
    work = env.tmp.joinpath(*LONG)
    slug = _slug(work)
    _setup(env, work, slug[:200] + "-000other", files=(("other.jsonl", 400_000),))
    r = _run(env, bash, work)
    assert r.returncode == 1 and FULL not in r.stdout


def test_prefers_this_sessions_transcript_over_the_newest(env, bash):
    work = env.tmp / "w"
    # s-mine is older and big (40%); s-other is newer and small (10%).
    _setup(env, work, _slug(work), files=(("s-mine.jsonl", 2_800_000), ("s-other.jsonl", 400_000)))
    assert "10%" in _run(env, bash, work).stdout
    r = _run(env, bash, work, extra={"CLAUDE_CODE_SESSION_ID": "s-mine"})
    assert "40%" in r.stdout, r.stdout


def test_physical_path_is_tried_when_launched_through_a_symlink(env, bash):
    real = env.tmp / "real proj"
    link = env.tmp / "link"
    _setup(env, real, _slug(real.resolve()))
    link.symlink_to(real)
    r = _run(env, bash, link)
    assert r.returncode == 0 and FULL in r.stdout, r.stderr


def test_logical_path_wins_when_both_exist(env, bash):
    real = env.tmp / "real"
    link = env.tmp / "link"
    _setup(env, real, _slug(real.resolve()), files=(("a.jsonl", 2_800_000),))   # 40%
    link.symlink_to(real)
    _setup(env, link, _slug(link), files=(("b.jsonl", 400_000),))              # 10%
    assert "10%" in _run(env, bash, link).stdout


def test_respects_claude_config_dir(env, bash):
    work = env.tmp / "w"
    cfg = env.tmp / "cfg"
    _setup(env, work, _slug(work), config=cfg)
    r = _run(env, bash, work, extra={"CLAUDE_CONFIG_DIR": str(cfg)})
    assert r.returncode == 0 and FULL in r.stdout, r.stderr


def test_no_project_dir_says_so_and_exits_1(env, bash):
    work = env.tmp / "elsewhere"
    work.mkdir()
    (env.claude / "projects" / "-some-other-project").mkdir(parents=True)
    (env.claude / "projects" / "-some-other-project" / "x.jsonl").write_text("{}")
    r = _run(env, bash, work)
    assert r.returncode == 1
    assert FULL not in r.stdout + r.stderr and "░" not in r.stdout + r.stderr
    assert _slug(work) in r.stderr


def test_project_dir_without_transcripts_exits_1(env, bash):
    work = env.tmp / "w"
    _setup(env, work, _slug(work), files=())
    r = _run(env, bash, work)
    assert r.returncode == 1 and "░" not in r.stdout


def test_flags(env, bash):
    work = env.tmp / "w"
    work.mkdir()
    assert _run(env, bash, work, args=["--help"]).returncode == 0
    assert _run(env, bash, work, args=["--bogus"]).returncode == 2
