"""Tests for the plan-week launchd scripts (#214, #146).

Every external command is a stub executable in a tmp dir that appends its argv to a log file,
so nothing here touches the real launchctl, osascript, gh, ~/Library or ~/.local/share.
"""
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from gbtest import TEST_CFG, cfg_copy, write_config

PLUGIN = Path(__file__).resolve().parent.parent
SKILL = PLUGIN / "skills" / "plan-week"
SCRIPTS = SKILL / "scripts"
PREFIX = TEST_CFG["plan_week"]["launchd"]["label_prefix"]
SYNC = f"{PREFIX}-sync"
WATCHDOG = f"{PREFIX}-watchdog"
T0 = 1_800_000_000          # arbitrary fixed "now"
HOUR = 3600


class Env:
    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.la = tmp / "LaunchAgents"
        self.state = tmp / "state"
        self.logs = tmp / "logs"
        self.bin = tmp / "bin"
        self.cfg_home = tmp / "launchd-config"
        self.cache_home = tmp / "launchd-cache"
        self.link = tmp / "share" / "github-board" / "current"
        for d in (self.home, self.bin):
            d.mkdir()
        self.set_config(TEST_CFG)
        self.calls = {n: tmp / f"{n}.calls" for n in ("launchctl", "osascript", "python")}
        cnt = tmp / "bootstrap.count"
        self._stub("launchctl", 'if [ "$1" = print ]; then exit "${LAUNCHCTL_PRINT_RC:-0}"; fi\n'
                                'if [ "$1" = bootstrap ]; then\n'
                                f'  c=$(cat "{cnt}" 2>/dev/null || echo 0); echo $((c+1)) > "{cnt}"\n'
                                '  if [ "$c" -lt "${LAUNCHCTL_BOOTSTRAP_FAILS:-0}" ]; then exit 5; fi\n'
                                '  exit "${LAUNCHCTL_BOOTSTRAP_RC:-0}"\n'
                                'fi\n')
        self._stub("osascript", "")
        self._stub("python", 'if [ -n "${PY_STDERR:-}" ]; then printf "%b" "$PY_STDERR" >&2; fi\n'
                             'exit "${PY_RC:-0}"\n')
        self.extra = {}

    def set_config(self, cfg):
        write_config(self.cfg_home, cfg)

    def _stub(self, name, body):
        path = self.bin / name
        path.write_text(f'#!/bin/bash\necho "$@" >> "{self.calls[name]}"\n{body}')
        path.chmod(0o755)

    def env(self, **kw):
        e = {"PATH": os.environ["PATH"], "HOME": str(self.home),
             "LAUNCHCTL": str(self.bin / "launchctl"), "OSASCRIPT": str(self.bin / "osascript"),
             "PYTHON": str(self.bin / "python"), "LA_DIR": str(self.la),
             "STATE_DIR": str(self.state), "LOG_DIR": str(self.logs), "NOW": str(T0),
             "BOOTSTRAP_RETRY_SLEEP": "0", "GB_PYTHON": sys.executable,
             "XDG_CONFIG_HOME": str(self.cfg_home), "XDG_CACHE_HOME": str(self.cache_home),
             "GITHUB_BOARD_LINK": str(self.link)}
        e.update(self.extra)
        e.update({k: str(v) for k, v in kw.items()})
        return e

    def run(self, script, *args, **kw):
        return self.run_path(SCRIPTS / script, *args, **kw)

    def run_path(self, path, *args, **kw):
        return subprocess.run(["bash", str(path), *args], env=self.env(**kw),
                              capture_output=True, text=True, timeout=60)

    def plist(self, label):
        with open(self.la / f"{label}.plist", "rb") as f:
            return plistlib.load(f)

    def log(self, name):
        p = self.calls[name]
        return p.read_text().splitlines() if p.exists() else []

    def reset_logs(self):
        for p in self.calls.values():
            p.unlink(missing_ok=True)

    def set_heartbeat(self, age_seconds):
        self.state.mkdir(parents=True, exist_ok=True)
        hb = self.state / "last-success"
        hb.touch()
        os.utime(hb, (T0 - age_seconds, T0 - age_seconds))


def foreign_plist(e, label, program):
    e.la.mkdir(parents=True, exist_ok=True)
    with open(e.la / f"{label}.plist", "wb") as f:
        plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash", program]}, f)


@pytest.fixture
def e(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def installed(e):
    """Both plists installed, launchctl log cleared."""
    assert e.run("install-launchd.sh").returncode == 0
    e.reset_logs()
    return e


# ---- install-launchd.sh ---------------------------------------------------

def test_install_renders_home_and_bootstraps_both_labels(e):
    r = e.run("install-launchd.sh")
    assert r.returncode == 0, r.stderr
    for label in (SYNC, WATCHDOG):
        text = (e.la / f"{label}.plist").read_text()
        assert "__HOME__" not in text
        assert str(e.home) in text
    uid = str(os.getuid())
    calls = e.log("launchctl")
    for label in (SYNC, WATCHDOG):
        assert f"bootout gui/{uid}/{label}" in calls
        assert f"bootstrap gui/{uid} {e.la / (label + '.plist')}" in calls
    assert e.logs.is_dir() and e.state.is_dir()


def test_install_only_installs_one_label(e):
    assert e.run("install-launchd.sh", "--only", WATCHDOG).returncode == 0
    assert (e.la / f"{WATCHDOG}.plist").exists()
    assert not (e.la / f"{SYNC}.plist").exists()
    assert all(SYNC not in c for c in e.log("launchctl"))


def test_install_ignores_bootout_failure_but_reports_bootstrap_failure(e):
    r = e.run("install-launchd.sh", "--only", SYNC, LAUNCHCTL_BOOTSTRAP_RC=5)
    assert r.returncode == 1 and "bootstrap failed" in r.stderr


def test_install_rejects_unknown_label(e):
    assert e.run("install-launchd.sh", "--only", "nope").returncode == 2


def test_check_passes_when_installed_and_writes_nothing(installed):
    before = sorted(p.name for p in installed.la.iterdir())
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 0, r.stdout
    assert all(c.startswith("print ") for c in installed.log("launchctl"))   # reads only
    assert sorted(p.name for p in installed.la.iterdir()) == before


def test_check_fails_when_a_plist_is_missing(installed):
    (installed.la / f"{SYNC}.plist").unlink()
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "MISSING" in r.stdout
    assert not (installed.la / f"{SYNC}.plist").exists()      # --check never writes


def test_check_fails_when_a_plist_differs(installed):
    p = installed.la / f"{WATCHDOG}.plist"
    p.write_text(p.read_text().replace("3600", "60"))
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "DIFFERS" in r.stdout


def test_check_fails_when_a_label_is_not_loaded(installed):
    r = installed.run("install-launchd.sh", "--check", LAUNCHCTL_PRINT_RC=1)
    assert r.returncode == 1
    assert f"NOT LOADED {SYNC}" in r.stdout and f"NOT LOADED {WATCHDOG}" in r.stdout
    assert not any(c.startswith(("bootstrap", "bootout")) for c in installed.log("launchctl"))


def test_check_passes_only_when_loaded(installed):
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 0 and "NOT LOADED" not in r.stdout
    uid = str(os.getuid())
    assert f"print gui/{uid}/{SYNC}" in installed.log("launchctl")


def test_install_retries_bootstrap_up_to_three_times(e):
    r = e.run("install-launchd.sh", "--only", SYNC, LAUNCHCTL_BOOTSTRAP_FAILS=2)
    assert r.returncode == 0, r.stderr
    assert len([c for c in e.log("launchctl") if c.startswith("bootstrap")]) == 3
    e.reset_logs()
    (e.calls["launchctl"].parent / "bootstrap.count").unlink()
    r = e.run("install-launchd.sh", "--only", SYNC, LAUNCHCTL_BOOTSTRAP_RC=5)
    assert r.returncode == 1 and "bootstrap failed" in r.stderr
    assert len([c for c in e.log("launchctl") if c.startswith("bootstrap")]) == 3


def test_install_no_reload_writes_the_plist_and_never_touches_launchctl(e):
    r = e.run("install-launchd.sh", "--only", WATCHDOG, "--no-reload")
    assert r.returncode == 0, r.stderr
    assert (e.la / f"{WATCHDOG}.plist").exists()
    assert e.log("launchctl") == []


# ---- run-sync.sh ----------------------------------------------------------

def test_run_sync_success_touches_heartbeat_and_removes_last_error(installed):
    installed.state.mkdir(exist_ok=True)
    (installed.state / "last-error").write_text("old\n")
    r = installed.run("run-sync.sh")
    assert r.returncode == 0
    assert (installed.state / "last-success").exists()
    assert not (installed.state / "last-error").exists()
    assert installed.log("osascript") == []
    assert installed.log("python")[0].endswith("weekly-focus.py sync")


def test_run_sync_failure_writes_last_error_notifies_and_exits_nonzero(installed):
    stderr = "".join(f"line {i}\\n" for i in range(30))
    r = installed.run("run-sync.sh", PY_RC=2, PY_STDERR=stderr)
    assert r.returncode == 2
    assert not (installed.state / "last-success").exists()
    err = (installed.state / "last-error").read_text().splitlines()
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ sync failed \(exit 2\)", err[0])
    assert err[-1] == "line 29" and len(err) == 21          # header + last 20 lines
    notes = installed.log("osascript")
    assert len(notes) == 1 and "sync failed" in notes[0]
    assert "line 29" in (installed.logs / "sync.err.log").read_text()


def test_run_sync_failure_does_not_remove_an_existing_heartbeat(installed):
    installed.set_heartbeat(HOUR)
    installed.run("run-sync.sh", PY_RC=1)
    assert (installed.state / "last-success").exists()


SKIP_MSG = "weekly-focus: skipped: GraphQL budget low (12 left, resets 20:05)\\n"


def test_run_sync_exit_3_is_a_skip_not_a_failure(installed):
    installed.set_heartbeat(5 * HOUR)
    hb = installed.state / "last-success"
    before = hb.stat().st_mtime
    (installed.state / "last-error").write_text("old error\n")
    r = installed.run("run-sync.sh", PY_RC=3, PY_STDERR=SKIP_MSG)
    assert r.returncode == 0
    assert hb.stat().st_mtime == before                         # heartbeat not touched
    assert (installed.state / "last-error").read_text() == "old error\n"   # not written or removed
    assert installed.log("osascript") == []                     # no notification
    log = (installed.logs / "sync.log").read_text()
    assert "sync skipped" in log and "budget low (12 left" in log
    assert "FAILED" not in log


def test_run_sync_exit_3_writes_no_last_error_when_there_was_none(installed):
    installed.run("run-sync.sh", PY_RC=3, PY_STDERR=SKIP_MSG)
    assert not (installed.state / "last-error").exists()
    assert not (installed.state / "last-success").exists()


@pytest.mark.parametrize("rc", [1, 2, 4, 127])
def test_run_sync_other_non_zero_exits_stay_failures(installed, rc):
    r = installed.run("run-sync.sh", PY_RC=rc)
    assert r.returncode == rc
    assert (installed.state / "last-error").exists()
    assert any("sync failed" in n for n in installed.log("osascript"))


def test_repeated_skips_leave_the_heartbeat_old_so_the_watchdog_raises_the_stale_alert(installed):
    installed.set_heartbeat(20 * HOUR)
    for i in range(7):                                  # 07:00 and 18:00 runs that all skip
        installed.run("run-sync.sh", NOW=T0 + i * 3600, PY_RC=3, PY_STDERR=SKIP_MSG)
    assert installed.log("osascript") == []
    r = installed.run("watchdog.sh", NOW=T0 + 7 * HOUR)     # heartbeat is now 27h old
    assert r.returncode == 0
    notes = installed.log("osascript")
    assert len(notes) == 1 and "sync stale" in notes[0] and "27h" in notes[0]
    assert "sync failed" not in notes[0]


def test_run_sync_reinstalls_an_unloaded_watchdog(installed):
    r = installed.run("run-sync.sh", LAUNCHCTL_PRINT_RC=1)
    assert r.returncode == 0
    uid = str(os.getuid())
    calls = installed.log("launchctl")
    assert f"print gui/{uid}/{WATCHDOG}" in calls
    assert f"bootstrap gui/{uid} {installed.la / (WATCHDOG + '.plist')}" in calls
    assert not any(SYNC in c and c.startswith("bootstrap") for c in calls)
    assert any("watchdog restored" in n for n in installed.log("osascript"))


def test_run_sync_reports_a_failed_watchdog_reinstall_and_never_says_restored(installed):
    r = installed.run("run-sync.sh", LAUNCHCTL_PRINT_RC=1, LAUNCHCTL_BOOTSTRAP_RC=5)
    assert r.returncode == 0
    notes = installed.log("osascript")
    assert len(notes) == 1 and "reinstall FAILED" in notes[0]
    assert not any("restored" in n for n in notes)
    assert str(installed.logs / "sync.log") in notes[0]
    assert "reinstall FAILED" in (installed.logs / "sync.log").read_text()


def test_run_sync_leaves_a_loaded_watchdog_alone(installed):
    installed.run("run-sync.sh")
    assert not any(c.startswith("bootstrap") for c in installed.log("launchctl"))


# ---- watchdog.sh ----------------------------------------------------------

def test_watchdog_fresh_heartbeat_is_quiet(installed):
    installed.set_heartbeat(2 * HOUR)
    r = installed.run("watchdog.sh")
    assert r.returncode == 0
    assert installed.log("osascript") == []
    assert len(r.stdout.strip().splitlines()) == 1
    assert "ok=2h" in r.stdout


def test_watchdog_stale_heartbeat_notifies_with_last_error_line(installed):
    installed.set_heartbeat(27 * HOUR)
    (installed.state / "last-error").write_text("2026-09-29T07:00:00Z sync failed (exit 1)\nboom\n")
    r = installed.run("watchdog.sh")
    assert r.returncode == 0
    notes = installed.log("osascript")
    assert len(notes) == 1
    assert "27h" in notes[0] and "sync failed (exit 1)" in notes[0] and "boom" not in notes[0]


def test_watchdog_heartbeat_just_under_limit_is_quiet(installed):
    installed.set_heartbeat(26 * HOUR - 1)
    installed.run("watchdog.sh")
    assert installed.log("osascript") == []


def test_watchdog_missing_heartbeat_notifies(installed):
    old = installed.la / f"{SYNC}.plist"
    os.utime(old, (T0 - 30 * HOUR, T0 - 30 * HOUR))
    r = installed.run("watchdog.sh")
    assert r.returncode == 0
    notes = installed.log("osascript")
    assert len(notes) == 1 and "No successful sync recorded" in notes[0]


def test_watchdog_rate_limits_each_alert_to_once_per_six_hours(installed):
    installed.set_heartbeat(40 * HOUR)
    installed.run("watchdog.sh", NOW=T0)
    installed.run("watchdog.sh", NOW=T0 + HOUR)
    installed.run("watchdog.sh", NOW=T0 + 6 * HOUR - 1)
    assert len(installed.log("osascript")) == 1
    installed.run("watchdog.sh", NOW=T0 + 6 * HOUR)
    assert len(installed.log("osascript")) == 2


def test_watchdog_alert_kinds_are_rate_limited_independently(installed):
    (installed.la / f"{WATCHDOG}.plist").unlink()
    installed.set_heartbeat(40 * HOUR)
    installed.run("watchdog.sh")
    notes = installed.log("osascript")
    assert len(notes) == 2      # restored + stale, each once


def test_watchdog_missing_plist_calls_install_only(installed):
    installed.set_heartbeat(HOUR)
    (installed.la / f"{SYNC}.plist").unlink()
    r = installed.run("watchdog.sh")
    assert r.returncode == 0
    assert (installed.la / f"{SYNC}.plist").exists()
    uid = str(os.getuid())
    boots = [c for c in installed.log("launchctl") if c.startswith("bootstrap")]
    assert boots == [f"bootstrap gui/{uid} {installed.la / (SYNC + '.plist')}"]
    assert any("restored" in n for n in installed.log("osascript"))


def test_watchdog_never_boots_itself_out_when_its_own_plist_is_missing(installed):
    installed.set_heartbeat(HOUR)
    (installed.la / f"{WATCHDOG}.plist").unlink()
    r = installed.run("watchdog.sh")
    assert r.returncode == 0
    assert (installed.la / f"{WATCHDOG}.plist").exists()          # rewritten
    assert not any(c.startswith(("bootout", "bootstrap")) and WATCHDOG in c
                   for c in installed.log("launchctl"))
    assert any("restored" in n for n in installed.log("osascript"))


def test_watchdog_failed_reinstall_alerts_reinstall_failed_not_restored(installed):
    installed.set_heartbeat(HOUR)
    (installed.la / f"{SYNC}.plist").unlink()
    r = installed.run("watchdog.sh", LAUNCHCTL_BOOTSTRAP_RC=5)
    assert r.returncode == 0
    notes = installed.log("osascript")
    assert any("reinstall FAILED" in n and SYNC in n for n in notes)
    assert not any("restored" in n for n in notes)
    assert "reinstall-failed" in r.stdout
    assert "watchdog.log" in " ".join(notes)


def test_watchdog_failed_unload_reinstall_alerts_reinstall_failed(installed):
    installed.set_heartbeat(HOUR)
    r = installed.run("watchdog.sh", LAUNCHCTL_PRINT_RC=1, LAUNCHCTL_BOOTSTRAP_RC=5)
    notes = installed.log("osascript")
    assert any("reinstall FAILED" in n for n in notes)
    assert not any("sync not loaded" in n for n in notes)


def test_watchdog_missing_heartbeat_is_pending_while_the_sync_plist_is_young(installed):
    plist = installed.la / f"{SYNC}.plist"
    os.utime(plist, (T0 - 2 * HOUR, T0 - 2 * HOUR))
    r = installed.run("watchdog.sh")
    assert installed.log("osascript") == []
    assert "stale=pending" in r.stdout


def test_watchdog_missing_heartbeat_alerts_once_the_sync_plist_is_old(installed):
    plist = installed.la / f"{SYNC}.plist"
    os.utime(plist, (T0 - 26 * HOUR, T0 - 26 * HOUR))
    installed.run("watchdog.sh")
    assert any("No successful sync recorded" in n for n in installed.log("osascript"))


def test_watchdog_unloaded_sync_job_is_reinstalled(installed):
    installed.set_heartbeat(HOUR)
    r = installed.run("watchdog.sh", LAUNCHCTL_PRINT_RC=1)
    assert r.returncode == 0
    uid = str(os.getuid())
    calls = installed.log("launchctl")
    assert f"print gui/{uid}/{SYNC}" in calls
    assert f"bootstrap gui/{uid} {installed.la / (SYNC + '.plist')}" in calls
    assert any("sync not loaded" in n for n in installed.log("osascript"))


def test_watchdog_always_exits_zero_even_when_notify_and_install_fail(installed):
    installed.set_heartbeat(40 * HOUR)
    (installed.la / f"{SYNC}.plist").unlink()
    r = installed.run("watchdog.sh", OSASCRIPT="/nonexistent/osascript",
                      LAUNCHCTL_BOOTSTRAP_RC=1, LAUNCHCTL_PRINT_RC=1)
    assert r.returncode == 0


# ---- static checks --------------------------------------------------------

def test_skill_frontmatter_name_matches_directory():
    text = (SKILL / "SKILL.md").read_text()
    m = re.match(r"---\nname: (.+)\n", text)
    assert m and m.group(1).strip() == SKILL.name == "plan-week"


@pytest.mark.parametrize("kind", ["sync", "watchdog"])
def test_plist_templates_have_no_keepalive_and_use_placeholders(kind):
    text = (SKILL / "launchd" / f"{kind}.plist.template").read_text()
    script = "run-sync.sh" if kind == "sync" else "watchdog.sh"
    assert "KeepAlive" not in text and ".claude" not in text
    assert "<string>__LABEL__</string>" in text and f"__SCRIPTS__/{script}" in text
    assert ("RunAtLoad" in text) == (kind == "watchdog")
    assert ("__CALENDAR__" in text) == (kind == "sync")


def test_only_the_two_generic_templates_exist():
    assert sorted(p.name for p in (SKILL / "launchd").iterdir()) == [
        "sync.plist.template", "watchdog.plist.template"]


@pytest.mark.parametrize("label", [SYNC, WATCHDOG])
def test_rendered_plists_parse_and_run_through_the_link(e, label):
    assert e.run("install-launchd.sh", "--no-reload").returncode == 0
    d = e.plist(label)
    assert d["Label"] == label
    assert d["ProgramArguments"][1].startswith(f"{e.link}/skills/plan-week/scripts/")
    assert d["EnvironmentVariables"]["XDG_CONFIG_HOME"] == str(e.cfg_home)
    assert d["EnvironmentVariables"]["XDG_CACHE_HOME"] == str(e.cache_home)
    if shutil.which("plutil"):
        r = subprocess.run(["plutil", "-lint", str(e.la / f"{label}.plist")], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


def test_sync_times_come_from_the_config(e):
    c = cfg_copy(); c["plan_week"]["launchd"]["times"] = ["06:30", "21:05"]
    e.set_config(c)
    assert e.run("install-launchd.sh", "--no-reload").returncode == 0
    assert e.plist(SYNC)["StartCalendarInterval"] == [{"Hour": 6, "Minute": 30}, {"Hour": 21, "Minute": 5}]


# ---- stable link and takeover (#146) ----------------------------------------

def test_install_points_the_link_at_this_plugin(e):
    assert e.run("install-launchd.sh").returncode == 0
    assert e.link.is_symlink() and e.link.resolve() == PLUGIN.resolve()


def test_install_re_points_an_old_link(e, tmp_path):
    old = tmp_path / "old-version"
    old.mkdir()
    e.link.parent.mkdir(parents=True)
    e.link.symlink_to(old)
    assert e.run("install-launchd.sh").returncode == 0
    assert e.link.resolve() == PLUGIN.resolve()


def test_install_run_through_the_link_never_points_the_link_at_itself(e):
    assert e.run("install-launchd.sh", "--no-reload").returncode == 0
    r = e.run_path(e.link / "skills" / "plan-week" / "scripts" / "install-launchd.sh", "--no-reload")
    assert r.returncode == 0, r.stderr
    assert os.readlink(e.link) == str(PLUGIN.resolve())


def test_takeover_is_refused_when_another_copy_owns_a_plist(e):
    other = "/Users/someone/old-skills/weekly-focus/scripts/run-sync.sh"
    foreign_plist(e, SYNC, other)
    before = (e.la / f"{SYNC}.plist").read_bytes()
    r = e.run("install-launchd.sh")
    assert r.returncode == 3
    assert other in r.stderr and "--takeover" in r.stderr
    assert (e.la / f"{SYNC}.plist").read_bytes() == before
    assert not (e.la / f"{WATCHDOG}.plist").exists()
    assert not e.link.exists() and e.log("launchctl") == []


def test_takeover_flag_hands_the_job_over(e):
    foreign_plist(e, SYNC, "/Users/someone/old-skills/weekly-focus/scripts/run-sync.sh")
    r = e.run("install-launchd.sh", "--takeover")
    assert r.returncode == 0, r.stderr
    assert e.plist(SYNC)["ProgramArguments"][1] == f"{e.link}/skills/plan-week/scripts/run-sync.sh"


def test_an_unreadable_plist_blocks_too(e):
    e.la.mkdir(parents=True)
    (e.la / f"{SYNC}.plist").write_bytes(b"\x00not a plist")
    r = e.run("install-launchd.sh")
    assert r.returncode == 3 and "cannot read" in r.stderr


def test_our_own_plist_is_not_a_foreign_owner(e):
    assert e.run("install-launchd.sh").returncode == 0
    assert e.run("install-launchd.sh").returncode == 0


def test_link_path_that_is_a_real_directory_is_refused(e):
    e.link.mkdir(parents=True)
    (e.link / "keep.txt").write_text("mine")
    r = e.run("install-launchd.sh")
    assert r.returncode == 3 and "not a symlink" in r.stderr
    assert (e.link / "keep.txt").read_text() == "mine" and sorted(p.name for p in e.link.iterdir()) == ["keep.txt"]
    assert not e.la.exists() or list(e.la.iterdir()) == []


def test_launchd_disabled_in_config_installs_nothing(e):
    c = cfg_copy(); c["plan_week"]["launchd"]["enabled"] = False
    e.set_config(c)
    r = e.run("install-launchd.sh")
    assert r.returncode == 2 and "enabled is false" in r.stderr
    assert not e.la.exists() and not e.link.exists()


def test_missing_config_exits_4(e):
    (e.cfg_home / "github-board" / "config.json").unlink()
    r = e.run("install-launchd.sh")
    assert r.returncode == 4 and "plan-week init" in r.stderr


def test_check_fails_on_a_missing_link(installed):
    installed.link.unlink()
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "MISSING LINK" in r.stdout


def test_check_fails_on_a_dangling_link(installed, tmp_path):
    installed.link.unlink()
    installed.link.symlink_to(tmp_path / "gone")
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "DANGLING LINK" in r.stdout


def test_check_fails_on_a_link_without_plan_week(installed, tmp_path):
    empty = tmp_path / "empty-plugin"
    empty.mkdir()
    installed.link.unlink()
    installed.link.symlink_to(empty)
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "BAD LINK" in r.stdout


def test_check_reports_a_real_directory_at_the_link_path(installed):
    installed.link.unlink()
    installed.link.mkdir()
    r = installed.run("install-launchd.sh", "--check")
    assert r.returncode == 1 and "NOT A LINK" in r.stdout


# ---- a missing or broken config under launchd (#146) --------------------------

def test_run_sync_without_a_config_notifies_and_records_the_error(installed):
    (installed.cfg_home / "github-board" / "config.json").unlink()
    r = installed.run("run-sync.sh")
    assert r.returncode == 4
    assert installed.log("python") == []                     # sync never ran
    assert any("config" in c for c in installed.log("osascript"))
    assert "plan-week init" in (installed.state / "last-error").read_text()


def test_watchdog_with_a_broken_config_alerts_once_per_six_hours(installed):
    installed.set_config("{not json")
    r = installed.run("watchdog.sh")
    assert r.returncode == 2
    assert len([c for c in installed.log("osascript") if "config" in c]) == 1
    installed.run("watchdog.sh", NOW=T0 + HOUR)
    assert len([c for c in installed.log("osascript") if "config" in c]) == 1
    installed.run("watchdog.sh", NOW=T0 + 7 * HOUR)
    assert len([c for c in installed.log("osascript") if "config" in c]) == 2


def test_install_without_a_config_does_not_notify(e):
    (e.cfg_home / "github-board" / "config.json").unlink()
    assert e.run("install-launchd.sh").returncode == 4
    assert e.log("osascript") == []
