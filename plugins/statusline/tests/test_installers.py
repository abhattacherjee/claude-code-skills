"""install.sh and generate-statusline.sh: the write guard and a safe settings.json update (#158).

Exit codes for both: 0 success, 1 write failed, 2 bad input (flags, items, settings.json
that is not one JSON object), 3 refused (target script not written by this plugin).
"""
import json
import os
import shutil
import subprocess

import pytest

from sltest import (DEFAULT_CMD, GENERATE, INSTALL, MARKER, MOCK_JSON, REFERENCE, USER_SCRIPT,
                    backups, leftovers, snapshot, stub, tool_dir)

ITEMS = "model,dir,context-bar,cost"


def install(env, bash, *args, **kw):
    return env.run(bash, INSTALL, *args, **kw)


def generate(env, bash, *args, **kw):
    return env.run(bash, GENERATE, *args, **kw)


def statusline(settings):
    return json.loads(settings.read_text())["statusLine"]


# ── install.sh: the script ──────────────────────────────────────────────────

def test_install_into_an_empty_home(env, bash):
    r = install(env, bash)
    assert r.returncode == 0, r.stderr
    lines = env.script.read_text().splitlines()
    assert lines[1] == MARKER
    assert env.script.read_text() == REFERENCE.read_text()
    assert statusline(env.settings) == {"type": "command", "command": DEFAULT_CMD}


def test_reference_script_carries_the_marker_on_line_2():
    assert REFERENCE.read_text().splitlines()[1] == MARKER


def test_install_refuses_the_users_own_script_and_leaves_settings_alone(env, bash):
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    env.settings.write_text('{"theme": "dark"}\n')
    script_before, settings_before = snapshot(env.script), snapshot(env.settings)
    r = install(env, bash)
    assert r.returncode == 3
    assert snapshot(env.script) == script_before
    assert snapshot(env.settings) == settings_before
    assert backups(env.script) == [] and backups(env.settings) == []
    assert "--force" in r.stderr


def test_install_force_replaces_the_users_script_after_a_backup(env, bash):
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    r = install(env, bash, "--force")
    assert r.returncode == 0, r.stderr
    assert env.script.read_text() == REFERENCE.read_text()
    [b] = backups(env.script)
    assert b.read_text() == USER_SCRIPT


def test_reinstall_of_identical_script_makes_no_backup(env, bash):
    assert install(env, bash).returncode == 0
    before = snapshot(env.script)
    r = install(env, bash)
    assert r.returncode == 0, r.stderr
    assert backups(env.script) == [] and snapshot(env.script) == before


def test_reinstall_over_a_changed_managed_script_backs_up(env, bash):
    assert install(env, bash).returncode == 0
    env.script.write_text(env.script.read_text() + "# local edit\n")
    assert install(env, bash).returncode == 0
    [b] = backups(env.script)
    assert b.read_text().endswith("# local edit\n")


def test_reinstall_with_a_different_mode_rewrites(env, bash):
    assert install(env, bash).returncode == 0
    env.script.chmod(0o600)
    assert install(env, bash).returncode == 0
    assert env.script.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("args", [["--bogus"], ["--force", "extra"]])
def test_install_bad_flags_exit_2_and_write_nothing(env, bash, args):
    r = install(env, bash, *args)
    assert r.returncode == 2
    assert not env.claude.exists()


def test_install_help_exits_0_and_writes_nothing(env, bash):
    r = install(env, bash, "--help")
    assert r.returncode == 0 and "--force" in r.stdout
    assert not env.claude.exists()


def test_install_without_jq_exits_1_and_writes_nothing(env):
    # Not parametrized over bash: the jq-less PATH holds the PATH bash only.
    env.path_only = str(tool_dir(env.tmp, exclude=("jq",)))
    r = install(env, "bash")
    assert r.returncode == 1
    assert "jq" in r.stderr
    assert not env.script.exists() and not env.settings.exists()


def test_failed_script_write_leaves_settings_alone(env, bash):
    env.claude.mkdir()
    env.settings.write_text('{"theme": "dark"}\n')
    before = snapshot(env.settings)
    env.path_prefix = [stub(env.tmp, "mv", "exit 1")]
    r = install(env, bash)
    assert r.returncode == 1
    assert not env.script.exists()
    assert snapshot(env.settings) == before


# ── install.sh: settings.json ───────────────────────────────────────────────

def test_settings_missing_but_dir_exists(env, bash):
    env.claude.mkdir()
    assert install(env, bash).returncode == 0
    assert json.loads(env.settings.read_text()) == {
        "statusLine": {"type": "command", "command": DEFAULT_CMD}}


@pytest.mark.parametrize("content", ["", "  \n\t\n"])
def test_settings_empty_or_blank_gets_statusline(env, bash, content):
    env.claude.mkdir()
    env.settings.write_text(content)
    r = install(env, bash)
    assert r.returncode == 0, r.stderr
    assert statusline(env.settings)["command"] == DEFAULT_CMD


@pytest.mark.parametrize("content", ['{"a": 1,', "not json", "[]", '"x"', "{} {}", "null"])
def test_settings_that_is_not_one_object_exits_2_byte_identical(env, bash, content):
    env.claude.mkdir()
    env.settings.write_text(content)
    before = snapshot(env.settings)
    r = install(env, bash)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert snapshot(env.settings) == before
    assert not env.script.exists()            # checked before the script is written
    assert backups(env.settings) == [] and leftovers(env.claude) == []


def test_settings_without_statusline_keeps_every_other_key(env, bash):
    env.claude.mkdir()
    original = {"theme": "dark", "permissions": {"allow": ["Bash(ls:*)"]}, "env": {"X": "é"}}
    env.settings.write_text(json.dumps(original, indent=2, ensure_ascii=False) + "\n")
    raw = env.settings.read_bytes()
    assert install(env, bash).returncode == 0
    got = json.loads(env.settings.read_text())
    assert got.pop("statusLine")["command"] == DEFAULT_CMD
    assert got == original
    [b] = backups(env.settings)
    assert b.read_bytes() == raw


def test_settings_with_another_statusline_is_replaced_after_a_backup(env, bash):
    env.claude.mkdir()
    env.settings.write_text('{"statusLine": {"type": "command", "command": "other"}}')
    assert install(env, bash).returncode == 0
    assert statusline(env.settings)["command"] == DEFAULT_CMD
    assert len(backups(env.settings)) == 1


def test_settings_already_right_is_not_rewritten(env, bash):
    env.claude.mkdir()
    env.settings.write_text(json.dumps({"statusLine": {"type": "command", "command": DEFAULT_CMD}}))
    before = snapshot(env.settings)
    assert install(env, bash).returncode == 0
    assert snapshot(env.settings) == before and backups(env.settings) == []


def test_settings_mode_is_kept(env, bash):
    env.claude.mkdir()
    env.settings.write_text("{}")
    env.settings.chmod(0o640)
    assert install(env, bash).returncode == 0
    assert env.settings.stat().st_mode & 0o777 == 0o640


def test_symlinked_settings_stays_a_symlink(env, bash):
    env.claude.mkdir()
    real = env.tmp / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text('{"theme": "dark"}')
    env.settings.symlink_to(real)
    assert install(env, bash).returncode == 0
    assert env.settings.is_symlink()
    assert json.loads(real.read_text())["statusLine"]["command"] == DEFAULT_CMD


def test_settings_write_failure_exits_1_settings_byte_identical(env, bash):
    env.claude.mkdir()
    env.settings.write_text('{"theme": "dark"}')
    before = snapshot(env.settings)
    env.path_prefix = [stub(env.tmp, "mv", 'for a; do dst=$a; done\n'
                                          'case "$dst" in *settings.json) exit 1;; esac\n'
                                          'exec "$REAL" "$@"')]
    r = install(env, bash)
    assert r.returncode == 1
    assert snapshot(env.settings) == before
    assert leftovers(env.claude) == []


# ── the installed script still runs ─────────────────────────────────────────

def test_installed_script_runs(env, bash):
    assert install(env, bash).returncode == 0
    r = subprocess.run([bash, str(env.script)], input=MOCK_JSON, capture_output=True, text=True,
                       env=env.env({"COLUMNS": "120"}), cwd=str(env.home), timeout=30)
    assert r.returncode == 0, r.stderr
    assert "Opus" in r.stdout and "42%" in r.stdout


# ── generate-statusline.sh (/statusline:create) ─────────────────────────────

def test_generate_writes_a_marked_script_that_runs(env, bash):
    r = generate(env, bash, "--items", ITEMS)
    assert r.returncode == 0, r.stderr
    assert env.script.read_text().splitlines()[1] == MARKER
    assert not env.settings.exists()              # no --install, no settings change
    out = subprocess.run([bash, str(env.script)], input=MOCK_JSON, capture_output=True,
                         text=True, env=env.env(), timeout=30)
    assert out.returncode == 0 and "Opus" in out.stdout and "$0.05" in out.stdout


def test_generate_refuses_the_users_own_script(env, bash):
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    before = snapshot(env.script)
    r = generate(env, bash, "--items", ITEMS)
    assert r.returncode == 3
    assert snapshot(env.script) == before


def test_generate_install_refuses_and_leaves_settings_alone(env, bash):
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    env.settings.write_text('{"statusLine": {"type": "command", "command": "mine"}}')
    script_before, settings_before = snapshot(env.script), snapshot(env.settings)
    r = generate(env, bash, "--items", ITEMS, "--install")
    assert r.returncode == 3
    assert snapshot(env.script) == script_before and snapshot(env.settings) == settings_before


def test_generate_install_force_backs_up_and_points_settings_at_the_default(env, bash):
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    r = generate(env, bash, "--items", ITEMS, "--install", "--force")
    assert r.returncode == 0, r.stderr
    [b] = backups(env.script)
    assert b.read_text() == USER_SCRIPT
    assert statusline(env.settings)["command"] == DEFAULT_CMD


def test_generate_install_creates_missing_settings(env, bash):
    r = generate(env, bash, "--items", ITEMS, "--install")
    assert r.returncode == 0, r.stderr
    assert statusline(env.settings)["command"] == DEFAULT_CMD


def test_generate_install_with_invalid_settings_exits_2_before_writing(env, bash):
    env.claude.mkdir()
    env.settings.write_text("{oops")
    before = snapshot(env.settings)
    r = generate(env, bash, "--items", ITEMS, "--install")
    assert r.returncode == 2
    assert snapshot(env.settings) == before and not env.script.exists()


def test_generate_output_path_with_spaces_is_quoted_in_settings(env, bash):
    target = env.tmp / "my dir" / "it's.sh"
    target.parent.mkdir()
    r = generate(env, bash, "--items", ITEMS, "--output", target, "--install")
    assert r.returncode == 0, r.stderr
    cmd = statusline(env.settings)["command"]
    # Run the settings command with this arm's bash as "bash" on PATH.
    shim = env.tmp / "bashbin"
    shim.mkdir()
    (shim / "bash").symlink_to(shutil.which(bash) if os.sep not in bash else bash)
    env.path_prefix = [shim]
    out = subprocess.run(["sh", "-c", 'bash -c "echo \\$BASH_VERSION" >&2; ' + cmd], input=MOCK_JSON,
                         capture_output=True, text=True, env=env.env(), timeout=30)
    if bash != "bash":
        assert out.stderr.startswith("3.2"), out.stderr
    assert out.returncode == 0 and "Opus" in out.stdout, (cmd, out.stderr)


def test_generate_relative_output_is_made_absolute_in_settings(env, bash):
    work = env.tmp / "work"
    work.mkdir()
    r = generate(env, bash, "--items", ITEMS, "--output", "sl.sh", "--install", cwd=work)
    assert r.returncode == 0, r.stderr
    assert statusline(env.settings)["command"] == f"bash {work}/sl.sh"


def test_generate_items_with_spaces_are_all_rendered(env, bash):
    assert generate(env, bash, "--items", "model, cost").returncode == 0
    out = subprocess.run([bash, str(env.script)], input=MOCK_JSON, capture_output=True,
                         text=True, env=env.env(), timeout=30)
    assert "Opus" in out.stdout and "$0.05" in out.stdout


@pytest.mark.parametrize("args", [
    [],                                   # --items is required
    ["--items"],                          # missing value
    ["--items", "model", "--bogus"],
    ["--items", "model,nope"],            # unknown item
    ["--items", "model", "--lines", "4"],
    ["--items", "model", "--output"],
])
def test_generate_bad_input_exits_2_and_writes_nothing(env, bash, args):
    r = generate(env, bash, *args)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert not env.claude.exists()


def test_generate_help_and_list_exit_0(env, bash):
    assert generate(env, bash, "--help").returncode == 0
    assert generate(env, bash, "--list").returncode == 0
    assert not env.claude.exists()


def test_settings_build_that_yields_bad_json_exits_1_settings_unchanged(env, bash):
    # jq "succeeds" but emits a truncated document: the new file is checked before the mv.
    env.claude.mkdir()
    env.settings.write_text('{"theme": "dark"}')
    before = snapshot(env.settings)
    body = ('case "$*" in *".statusLine = "*) printf \'{"theme"\'; exit 0;; esac\n'
            'exec "$REAL" "$@"')
    env.path_prefix = [stub(env.tmp, "jq", body)]
    r = install(env, bash)
    assert r.returncode == 1
    assert snapshot(env.settings) == before
    assert backups(env.settings) == [] and leftovers(env.claude) == []


def test_unreadable_settings_stops_before_anything_is_written(env, bash):
    # An unreadable settings.json is not "blank": treating it so wrote the script and then
    # failed on settings, leaving half an install.
    if os.geteuid() == 0:
        pytest.fail("run the suite as a normal user; root can read a mode-000 file")
    env.claude.mkdir()
    env.settings.write_text('{"theme": "dark"}')
    env.settings.chmod(0o000)
    try:
        r = install(env, bash)
        assert r.returncode == 1, (r.returncode, r.stderr)
        assert not env.script.exists()
        assert "read" in r.stderr
    finally:
        env.settings.chmod(0o644)
    assert env.settings.read_text() == '{"theme": "dark"}'
