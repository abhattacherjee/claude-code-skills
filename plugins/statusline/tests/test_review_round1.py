"""Round-1 review fixes for #158 (I1-I8, S1-S9)."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from sltest import (CONTEXT_BAR, DEFAULT_CMD, GENERATE, INSTALL, MARKER, MOCK_JSON, REFERENCE,
                    SKILLS, backups, leftovers, snapshot, stub, tool_dir)
from test_statusline_security import (generated, git, git_env, make_repos, payload,
                                      run_script)
from test_context_bar import _run as run_bar, _setup as bar_setup, _slug

ITEMS = "model,dir,context-bar,cost"


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def repos(tmp_path, home):
    return make_repos(tmp_path / "repos", git_env(home))


# ── I1: git-sync works without git, and in any order ────────────────────────

@pytest.mark.parametrize("items", ["git-sync,git", "git-sync", "git,git-sync", "git-sync,git-link,git"])
def test_git_sync_shows_arrows_whatever_the_item_order(tmp_path, home, repos, bash, items):
    script = generated(tmp_path, home, items, bash)
    r = run_script(script, payload(), repos["long-dirty-ahead"], git_env(home), bash=bash)
    assert r.returncode == 0, r.stderr
    assert "↑1" in r.stdout, r.stdout
    assert script.read_text().count("# ─── Git data") == 1


def test_no_unused_need_flags_in_generator():
    text = GENERATE.read_text()
    for flag in ("needs_cost", "needs_context", "needs_git_cache"):
        assert flag not in text
    assert "Only add if git wasn't already added" not in text


# ── I2: CLAUDE_CONFIG_DIR ───────────────────────────────────────────────────

def _cfg_cmd_runs(env, cmd, bash):
    out = subprocess.run(["sh", "-c", cmd], input=MOCK_JSON, capture_output=True, text=True,
                         env=env.env(), timeout=30)
    return out.returncode == 0 and "Opus" in out.stdout


def test_install_honours_claude_config_dir(env, bash):
    cfg = env.tmp / "my cfg"
    r = env.run(bash, INSTALL, extra={"CLAUDE_CONFIG_DIR": str(cfg)})
    assert r.returncode == 0, r.stderr
    script = cfg / "statusline-command.sh"
    assert script.read_text().splitlines()[1] == MARKER
    cmd = json.loads((cfg / "settings.json").read_text())["statusLine"]["command"]
    assert str(script) in cmd.replace("'", "")
    assert _cfg_cmd_runs(env, cmd, bash), cmd
    assert not env.claude.exists()


def test_generate_install_honours_claude_config_dir(env, bash):
    cfg = env.tmp / "cfg"
    r = env.run(bash, GENERATE, "--items", ITEMS, "--install", extra={"CLAUDE_CONFIG_DIR": str(cfg)})
    assert r.returncode == 0, r.stderr
    cmd = json.loads((cfg / "settings.json").read_text())["statusLine"]["command"]
    assert cmd == f"bash {cfg}/statusline-command.sh"
    assert _cfg_cmd_runs(env, cmd, bash)
    assert not env.claude.exists()


def test_default_config_dir_keeps_the_tilde_command(env, bash):
    r = env.run(bash, INSTALL, extra={"CLAUDE_CONFIG_DIR": str(env.claude)})
    assert r.returncode == 0
    assert json.loads(env.settings.read_text())["statusLine"]["command"] == DEFAULT_CMD


# ── I3: no jq / bad JSON at runtime ─────────────────────────────────────────

def _scripts(tmp_path, home, bash):
    return [REFERENCE, generated(tmp_path, home, "model,dir,context-bar,git,cost", bash)]


def test_missing_jq_at_runtime_says_so(tmp_path, home, repos, bash):
    scripts = _scripts(tmp_path, home, bash)
    env = git_env(home)
    env["PATH"] = str(tool_dir(tmp_path, exclude=("jq",)))
    for s in scripts:
        r = subprocess.run(["bash", str(s)], input=MOCK_JSON, capture_output=True, text=True,
                           env=env, cwd=str(repos["none"]), timeout=30)
        assert r.returncode == 0
        assert r.stdout == "statusline: jq not on PATH\n", (s.name, r.stdout)


@pytest.mark.parametrize("stdin", ["not json", "", '{"model":'])
def test_invalid_json_on_stdin_degrades_to_a_message(tmp_path, home, repos, bash, stdin):
    for s in _scripts(tmp_path, home, bash):
        r = subprocess.run([bash, str(s)], input=stdin, capture_output=True, text=True,
                           env=dict(git_env(home), COLUMNS="200"), cwd=str(repos["none"]), timeout=30)
        assert r.returncode == 0
        assert r.stdout == "statusline: no session data\n", (s.name, r.stdout)


# ── I4: unreadable target ───────────────────────────────────────────────────

def test_unreadable_target_is_reported_as_unreadable(env, bash):
    env.claude.mkdir()
    env.script.write_text("#!/bin/bash\n" + MARKER + "\n")
    env.script.chmod(0)
    src = env.tmp / "src.sh"
    src.write_text("#!/bin/bash\n" + MARKER + "\necho new\n")
    try:
        r = env.call_lib(bash, "write_statusline", src, env.script, 0)
    finally:
        env.script.chmod(0o644)
    assert r.returncode == 1
    assert "Cannot read" in r.stderr and "--force" not in r.stderr
    assert env.script.read_text() == "#!/bin/bash\n" + MARKER + "\n"


# ── I5, S1, S9: settings write failure, temp dirs ───────────────────────────

MV_FAILS_ON_SETTINGS = ('for a; do dst=$a; done\ncase "$dst" in *settings.json) exit 1;; esac\n'
                       'exec "$REAL" "$@"')


@pytest.mark.parametrize("script,args", [(INSTALL, []), (GENERATE, ["--items", ITEMS, "--install"])])
def test_settings_write_failure_exits_1_and_says_what_state_it_left(env, bash, script, args):
    env.claude.mkdir()
    env.settings.write_text('{"theme": "dark"}')
    before = snapshot(env.settings)
    env.path_prefix = [stub(env.tmp, "mv", MV_FAILS_ON_SETTINGS)]
    r = env.run(bash, script, *args)
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert snapshot(env.settings) == before
    assert env.script.exists()
    assert "statusline script written; settings.json unchanged" in r.stderr
    assert leftovers(env.claude) == []
    assert list((env.tmp / "tmpdir").iterdir()) == []


def test_settings_temp_file_is_made_next_to_settings_not_in_tmpdir(env, bash):
    r = env.run(bash, INSTALL, extra={"TMPDIR": str(env.tmp / "no-such-dir")})
    assert r.returncode == 0, r.stderr
    assert json.loads(env.settings.read_text())["statusLine"]["command"] == DEFAULT_CMD


def test_dangling_symlink_settings_stops_before_anything_is_written(env, bash):
    env.claude.mkdir()
    env.settings.symlink_to(env.tmp / "gone" / "settings.json")
    r = env.run(bash, INSTALL)
    assert r.returncode == 1
    assert "does not exist" in r.stderr
    assert not env.script.exists() and env.settings.is_symlink()
    assert not (env.tmp / "gone").exists()


def test_generate_install_with_unreadable_settings_writes_nothing(env, bash):
    env.claude.mkdir()
    env.settings.write_text("{}")
    env.settings.chmod(0)
    try:
        r = env.run(bash, GENERATE, "--items", ITEMS, "--install")
    finally:
        env.settings.chmod(0o644)
    assert r.returncode == 1
    assert not env.script.exists() and env.settings.read_text() == "{}"


# ── S2, S9: generator without python3, or with a step failing midway ────────

def test_generate_without_python3_exits_1_with_a_message(env):
    env.path_only = str(tool_dir(env.tmp, exclude=("python3",)))
    r = env.run("bash", GENERATE, "--items", ITEMS)
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "python3" in r.stderr
    assert not env.script.exists()


def test_generate_step_failing_midway_leaves_everything_unchanged(env, bash):
    env.claude.mkdir()
    env.script.write_text("#!/bin/bash\n" + MARKER + "\necho old\n")
    before = snapshot(env.script)
    env.path_prefix = [stub(env.tmp, "python3", 'echo "echo half"; exit 1')]
    r = env.run(bash, GENERATE, "--items", ITEMS, "--install")
    assert r.returncode == 1
    assert snapshot(env.script) == before and not env.settings.exists()
    assert list((env.tmp / "tmpdir").iterdir()) == []


# ── S3: context-bar session note ─────────────────────────────────────────────

def test_missing_session_transcript_is_noted_before_falling_back(env, bash):
    work = env.tmp / "w"
    bar_setup(env, work, _slug(work), files=(("other.jsonl", 400_000),))
    r = run_bar(env, bash, work, extra={"CLAUDE_CODE_SESSION_ID": "gone"})
    assert r.returncode == 0 and "10%" in r.stdout
    assert "gone.jsonl" in r.stderr and len(r.stderr.strip().splitlines()) == 1


def test_context_bar_doc_states_window_and_config_dir():
    text = (SKILLS / "context-bar" / "SKILL.md").read_text()
    assert "1M-token window" in text and "CLAUDE_CONFIG_DIR" in text


# ── S9: literal slugs through the script ────────────────────────────────────

@pytest.mark.parametrize("parts,suffix", [(["a.b c"], "-a-b-c"), (["my_proj"], "-my-proj"),
                                          (["café"], "-caf-"), (["x", ".hidden", "p"], "-x--hidden-p")])
def test_literal_slugs(env, bash, parts, suffix):
    base = env.tmp / "base"
    work = base.joinpath(*parts)
    bar_setup(env, work, _slug(base) + suffix)
    r = run_bar(env, bash, work)
    assert r.returncode == 0, r.stderr


# ── S4: branch name with a pipe ─────────────────────────────────────────────

def test_branch_with_a_pipe_does_not_shift_fields(tmp_path, home, repos, bash):
    env = git_env(home)
    repo = repos["develop-clean"]
    git(repo, "checkout", "-q", "-b", "a|b", env=env)
    script = generated(tmp_path, home, "git", bash)
    for _ in range(2):                     # fresh, then from the cache
        r = run_script(script, payload(), repo, env, bash=bash)
        assert r.returncode == 0 and "integer" not in r.stderr, r.stderr
        assert "a|b\x1b[0m" in r.stdout, repr(r.stdout)     # the whole name, nothing after it


# ── S6: settings merge ──────────────────────────────────────────────────────

def test_existing_statusline_keys_survive_and_old_command_is_printed(env, bash):
    env.claude.mkdir()
    env.settings.write_text(json.dumps({"statusLine": {"type": "command", "command": "old-cmd",
                                                        "padding": 2}}))
    r = env.run(bash, INSTALL)
    assert r.returncode == 0, r.stderr
    sl = json.loads(env.settings.read_text())["statusLine"]
    assert sl == {"type": "command", "command": DEFAULT_CMD, "padding": 2}
    assert "old-cmd" in r.stdout


def test_already_right_with_extra_keys_is_not_rewritten(env, bash):
    env.claude.mkdir()
    env.settings.write_text(json.dumps({"statusLine": {"type": "command", "command": DEFAULT_CMD,
                                                        "padding": 0}}))
    before = snapshot(env.settings)
    assert env.run(bash, INSTALL).returncode == 0
    assert snapshot(env.settings) == before and backups(env.settings) == []


# ── S8: missing model ───────────────────────────────────────────────────────

@pytest.mark.parametrize("item", ["model", "model-full"])
def test_missing_model_prints_no_null(tmp_path, home, repos, bash, item):
    script = generated(tmp_path, home, item + ",dir", bash)
    r = run_script(script, {"workspace": {"current_dir": "/x/y"}}, repos["none"], git_env(home), bash=bash)
    assert r.returncode == 0 and "null" not in r.stdout


# ── I8: a repo-local filter driver never runs ───────────────────────────────

def filter_repo(root: Path, env):
    repo = root / "filtered"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "trunk", env=env)
    marker = root / "FILTER-RAN"
    (repo / ".gitattributes").write_text("* filter=evil\n")
    git(repo, "config", "filter.evil.clean", f"sh -c 'touch {marker}; cat'", env=env)
    (repo / "f").write_text("hi\n")
    git(repo, "add", "f", ".gitattributes", env=env)
    git(repo, "commit", "-q", "-m", "init", env=env)
    marker.unlink(missing_ok=True) if hasattr(Path, "unlink") else None
    if marker.exists():
        marker.unlink()
    time.sleep(1.1)
    os.utime(repo / "f")                      # stat-dirty, same content
    # Probe: a plain git status does run the filter here.
    subprocess.run(["git", "-c", "core.fsmonitor=false", "status", "--porcelain"], cwd=str(repo),
                   env=env, capture_output=True)
    assert marker.exists()
    marker.unlink()
    os.utime(repo / "f", (time.time() + 5, time.time() + 5))
    return repo, marker


def test_three_tier_skips_status_when_a_local_filter_is_defined(tmp_path, home, bash):
    env = git_env(home)
    repo, marker = filter_repo(tmp_path, env)
    r = run_script(REFERENCE, payload(), repo, env, 200, bash)
    assert r.returncode == 0 and "trunk" in r.stdout
    assert not marker.exists()


def test_generated_git_skips_counts_when_a_local_filter_is_defined(tmp_path, home, bash):
    env = git_env(home)
    repo, marker = filter_repo(tmp_path, env)
    script = generated(tmp_path, home, "git,git-sync", bash)
    r = run_script(script, payload(), repo, env, bash=bash)
    assert r.returncode == 0 and "trunk" in r.stdout
    assert not marker.exists()


def test_global_filter_keeps_change_counts(tmp_path, home, repos, bash):
    # git-lfs installs its filter globally; counts must still show there.
    env = git_env(home)
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text("[filter \"lfs\"]\n\tclean = cat\n")
    env["GIT_CONFIG_GLOBAL"] = str(gcfg)
    r = run_script(REFERENCE, payload(), repos["long-dirty-ahead"], env, 200, bash)
    assert "~2" in r.stdout


# ── I6, I7, S7, S10: docs ───────────────────────────────────────────────────

def test_recipes_wrap_jq_values():
    import re
    doc = (SKILLS / "create" / "references" / "item-recipes.md").read_text()
    code = "\n".join(re.findall(r"```bash\n(.*?)```", doc, re.S))
    gen = GENERATE.read_text()
    # Every value from the session JSON is wrapped in num or clean, or is the generator's
    # own line, character for character (cost, tokens, the 200K flag).
    for line in code.splitlines():
        if 'jq -r' in line and "$(echo \"$input\"" in line:
            assert re.search(r'=\$\((num|clean) "\$\(echo', line) or line.strip() in gen, line
    assert 'elif [ -n "$BRANCH" ]' in doc
    assert '[ "$PCT" -gt 100 ] && PCT=100' in doc


def test_create_doc_does_not_overclaim_the_helpers():
    assert "do all of this" not in (SKILLS / "create" / "SKILL.md").read_text()


def test_context_bar_doc_has_one_rule_for_output():
    text = (SKILLS / "context-bar" / "SKILL.md").read_text()
    assert ("Run this command. On exit 0 the Bash output IS the result: do not echo or repeat it, "
            "and say nothing after it.") in text


def test_changelog_says_the_percentage_is_clamped_for_the_bar():
    text = (SKILLS.parent / "CHANGELOG.md").read_text()
    assert "the bar's percentage is clamped" in text


def test_comment_nits():
    ref = REFERENCE.read_text()
    assert '# e.g. "develop(⇡⇣)" or "feat/foo(~2|⇡1)"' in ref
    assert "# Args: $1=overhead (icons, separators, pct), $2=bar_width" in ref
    gen = GENERATE.read_text()
    assert "OSC 8, iTerm2/Kitty)" not in gen
    lib = (SKILLS.parent / "lib" / "write-statusline.sh").read_text()
    assert "directory" in lib.split("_sl_err()")[0]


def test_a_cache_file_in_the_old_one_line_format_is_not_read(tmp_path, home, repos, bash):
    # The 1.0.0-dev cache held "branch|staged|..." on one line under git-<cksum>. The
    # one-value-per-line reader would show that whole line as the branch, so the new
    # format uses a new file name.
    env = git_env(home)
    repo = repos["develop-clean"]
    key = subprocess.run("pwd -P | cksum | cut -d' ' -f1", shell=True, cwd=str(repo),
                         capture_output=True, text=True).stdout.strip()
    cache = home / ".cache" / "claude-statusline"
    cache.mkdir(parents=True)
    cache.chmod(0o700)
    (cache / f"git-{key}").write_text(f"{int(time.time())}\nstale|0|0|0|0\n")
    script = generated(tmp_path, home, "git", bash)
    r = run_script(script, payload(), repo, env, bash=bash)
    assert "develop" in r.stdout and "stale" not in r.stdout


@pytest.mark.parametrize("value", ['"bash old.sh"', "3", "[]", "true"])
@pytest.mark.parametrize("script,args", [(INSTALL, []), (GENERATE, ["--items", ITEMS, "--install"])])
def test_statusline_that_is_not_an_object_is_bad_input_before_any_write(env, bash, value, script, args):
    env.claude.mkdir()
    env.settings.write_text('{"statusLine": ' + value + '}')
    before = snapshot(env.settings)
    r = env.run(bash, script, *args)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert snapshot(env.settings) == before
    assert not env.script.exists()
    assert "statusLine" in r.stderr


def test_null_statusline_is_replaced(env, bash):
    env.claude.mkdir()
    env.settings.write_text('{"statusLine": null}')
    assert env.run(bash, INSTALL).returncode == 0
    assert json.loads(env.settings.read_text())["statusLine"]["command"] == DEFAULT_CMD


@pytest.mark.parametrize("url", ["https://user:SECRET-TOKEN@github.com/octo/repo.git",
                                 "https://SECRET-TOKEN@github.com/octo/repo",
                                 "http://user:SECRET-TOKEN@host/octo/repo"])
def test_git_link_never_shows_remote_credentials(tmp_path, home, repos, bash, url):
    env = git_env(home)
    repo = repos["develop-clean"]
    git(repo, "remote", "add", "origin", url, env=env)
    script = generated(tmp_path, home, "git-link", bash)
    r = run_script(script, payload(), repo, env, bash=bash)
    assert r.returncode == 0
    assert "SECRET" not in r.stdout and "user:" not in r.stdout and "@" not in r.stdout, r.stdout
    assert "\x1b]8;;http" in r.stdout and "/octo/repo\x07repo" in r.stdout, repr(r.stdout)


def test_recipe_git_link_strips_credentials():
    doc = (SKILLS / "create" / "references" / "item-recipes.md").read_text()
    assert "s#^([A-Za-z][A-Za-z0-9+.-]*://)[^/@]*@#\\1#" in doc


def test_lib_header_lists_each_functions_returns_under_it():
    lib = (SKILLS.parent / "lib" / "write-statusline.sh").read_text()
    head = lib.split("STATUSLINE_MARKER=")[0]
    upd = head.index("update_settings <settings.json>")
    quote = head.index("sl_shell_quote <path>")
    ret = head.index("Returns 0, 1 (write failed")
    assert upd < ret < quote


def test_changelog_percentage_claim_matches_the_ultra_narrow_tier():
    text = (SKILLS.parent / "CHANGELOG.md").read_text()
    assert "the printed percentage is shown as received" not in text
    assert "below 40 columns" in text
