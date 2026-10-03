"""lib/write-statusline.sh: write_statusline never destroys a script it did not write (#158).

Contract: write_statusline <source> <target> <force:0|1>
  absent target          -> write (temp file in the target's dir, then mv), exit 0
  target with the marker -> back up to <target>.bak-<UTC stamp>, then write, exit 0
  target without marker  -> force=0: untouched, exit 3; force=1: back up, write, exit 0
  backup or write fails  -> exit 1, target unchanged
  bad input              -> exit 2
"""
import datetime as dt
import re

from sltest import MARKER, USER_SCRIPT, backups, leftovers, snapshot, stub

NEW = "#!/bin/bash\n" + MARKER + "\necho new\n"
OLD_MANAGED = "#!/bin/bash\n" + MARKER + "\necho old\n"
STAMP = re.compile(r"\.bak-\d{8}T\d{6}Z(-\d+)?$")


def _short_cp(rc):
    """A cp that writes 5 bytes to any file under ~/.claude except a backup, then exits rc.

    Backups go through the real cp, so the test reaches the script write itself whether
    the code writes a temp file first or (wrongly) the target directly.
    """
    return ('src=; dst=; for a; do src=$dst; dst=$a; done\n'
            'case "$dst" in *.bak-*) ;; */.claude/*) head -c 5 "$src" > "$dst"; exit ' + str(rc) + ';; esac\n'
            'exec "$REAL" "$@"')


def _src(env, text=NEW):
    p = env.tmp / "src.sh"
    p.write_text(text)
    return p


def test_absent_target_is_written_exit_0(env, bash):
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 0, r.stderr
    assert env.script.read_text() == NEW
    assert env.script.stat().st_mode & 0o111            # executable
    assert backups(env.script) == []
    assert leftovers(env.claude) == []


def test_marked_target_is_backed_up_then_replaced(env, bash):
    env.claude.mkdir()
    env.script.write_text(OLD_MANAGED)
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 0, r.stderr
    assert env.script.read_text() == NEW
    [b] = backups(env.script)
    assert STAMP.search(b.name) and b.read_text() == OLD_MANAGED


def test_unmarked_target_is_refused_exit_3_and_left_untouched(env, bash):
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    before = snapshot(env.script)
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 3
    assert snapshot(env.script) == before
    assert backups(env.script) == [] and leftovers(env.claude) == []
    assert "--force" in r.stderr and str(env.script) in r.stderr


def test_marker_must_be_line_2_not_anywhere(env, bash):
    env.claude.mkdir()
    env.script.write_text("#!/bin/bash\n# mine\n" + MARKER + "\n")
    assert env.call_lib(bash, "write_statusline", _src(env), env.script, 0).returncode == 3


def test_unmarked_target_with_force_is_backed_up_then_replaced(env, bash):
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 1)
    assert r.returncode == 0, r.stderr
    assert env.script.read_text() == NEW
    [b] = backups(env.script)
    assert b.read_text() == USER_SCRIPT


def test_backup_failure_exits_1_and_leaves_target_unchanged(env, bash):
    env.claude.mkdir()
    env.script.write_text(OLD_MANAGED)
    before = snapshot(env.script)
    env.path_prefix = [stub(env.tmp, "cp", 'case "$*" in *.bak-*) exit 1;; esac\nexec "$REAL" "$@"')]
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 1
    assert snapshot(env.script) == before
    assert backups(env.script) == [] and leftovers(env.claude) == []


def test_short_backup_exits_1(env, bash):
    # cp "succeeds" but writes half the bytes (disk full): the backup is checked, not trusted.
    env.claude.mkdir()
    env.script.write_text(USER_SCRIPT)
    before = snapshot(env.script)
    body = ('for a; do dst=$a; done\ncase "$dst" in *.bak-*) head -c 100 "$2" > "$dst"; exit 0;; esac\n'
            'exec "$REAL" "$@"')
    env.path_prefix = [stub(env.tmp, "cp", body)]
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 1)
    assert r.returncode == 1
    assert snapshot(env.script) == before
    assert backups(env.script) == []


def test_write_failing_midway_exits_1_and_leaves_old_script(env, bash):
    env.claude.mkdir()
    env.script.write_text(OLD_MANAGED)
    before = snapshot(env.script)
    env.path_prefix = [stub(env.tmp, "cp", _short_cp(1))]
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 1
    assert snapshot(env.script) == before
    assert leftovers(env.claude) == []


def test_mv_failure_exits_1_and_leaves_old_script(env, bash):
    env.claude.mkdir()
    env.script.write_text(OLD_MANAGED)
    before = snapshot(env.script)
    env.path_prefix = [stub(env.tmp, "mv", "exit 1")]
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 1
    assert snapshot(env.script) == before
    assert leftovers(env.claude) == []


def test_source_without_marker_is_bad_input_exit_2(env, bash):
    r = env.call_lib(bash, "write_statusline", _src(env, "#!/bin/bash\necho x\n"), env.script, 0)
    assert r.returncode == 2
    assert not env.script.exists()


def test_bad_force_value_is_bad_input_exit_2(env, bash):
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, "yes")
    assert r.returncode == 2
    assert not env.script.exists()


def test_two_backups_in_the_same_second_are_both_kept(env, bash):
    env.claude.mkdir()
    env.script.write_text(OLD_MANAGED)
    env.path_prefix = [stub(env.tmp, "date", "echo 20261003T120000Z")]
    assert env.call_lib(bash, "write_statusline", _src(env), env.script, 0).returncode == 0
    second = "#!/bin/bash\n" + MARKER + "\necho second\n"
    assert env.call_lib(bash, "write_statusline", _src(env, second), env.script, 0).returncode == 0
    got = sorted(b.read_text() for b in backups(env.script))
    assert got == sorted([OLD_MANAGED, NEW])
    assert [b.name for b in backups(env.script)] == [
        "statusline-command.sh.bak-20261003T120000Z", "statusline-command.sh.bak-20261003T120000Z-1"]


def test_backup_stamp_is_utc_whatever_the_local_zone(env, bash):
    env.claude.mkdir()
    env.script.write_text(OLD_MANAGED)
    code = '. "$1"; write_statusline "$2" "$3" 0'
    import subprocess
    r = subprocess.run([bash, "-c", code, "_", str(__import__("sltest").LIB), str(_src(env)),
                        str(env.script)], capture_output=True, text=True,
                       env=env.env({"TZ": "Pacific/Kiritimati"}))  # UTC+14
    assert r.returncode == 0, r.stderr
    [b] = backups(env.script)
    stamp = dt.datetime.strptime(b.name.split(".bak-")[1], "%Y%m%dT%H%M%SZ")
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    assert abs((now - stamp).total_seconds()) < 300


def test_foreign_symlink_is_refused_and_the_link_kept(env, bash):
    env.claude.mkdir()
    real = env.tmp / "dotfiles" / "statusline.sh"
    real.parent.mkdir()
    real.write_text(USER_SCRIPT)
    env.script.symlink_to(real)
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 3
    assert env.script.is_symlink() and real.read_text() == USER_SCRIPT


def test_dangling_symlink_is_refused(env, bash):
    env.claude.mkdir()
    env.script.symlink_to(env.tmp / "nowhere" / "x.sh")
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 3
    assert env.script.is_symlink() and not (env.tmp / "nowhere").exists()


def test_managed_symlink_target_is_updated_through_the_link(env, bash):
    env.claude.mkdir()
    real = env.tmp / "dotfiles" / "statusline.sh"
    real.parent.mkdir()
    real.write_text(OLD_MANAGED)
    env.script.symlink_to(real)
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 0, r.stderr
    assert env.script.is_symlink() and real.read_text() == NEW
    [b] = backups(real)
    assert b.read_text() == OLD_MANAGED


def test_short_write_that_reports_success_exits_1_and_leaves_old_script(env, bash):
    # cp to the temp file exits 0 but writes 5 bytes (disk full): the temp file is checked.
    env.claude.mkdir()
    env.script.write_text(OLD_MANAGED)
    before = snapshot(env.script)
    env.path_prefix = [stub(env.tmp, "cp", _short_cp(0))]
    r = env.call_lib(bash, "write_statusline", _src(env), env.script, 0)
    assert r.returncode == 1
    assert snapshot(env.script) == before
    assert leftovers(env.claude) == []
