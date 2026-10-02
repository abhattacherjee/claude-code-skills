"""Tests for the weekly-focus launchd scripts and SKILL.md (#214).

Every external command is a stub executable in a tmp dir that appends its argv to a log file,
so nothing here touches the real launchctl, osascript, gh or ~/Library.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent / "skills" / "plan-week"
SCRIPTS = SKILL / "scripts"
SYNC = "com.abhattacherjee.weekly-focus-sync"
WATCHDOG = "com.abhattacherjee.weekly-focus-watchdog"
T0 = 1_800_000_000          # arbitrary fixed "now"
HOUR = 3600


class Env:
    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.la = tmp / "LaunchAgents"
        self.state = tmp / "state"
        self.logs = tmp / "logs"
        self.bin = tmp / "bin"
        for d in (self.home, self.bin):
            d.mkdir()
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

    def _stub(self, name, body):
        path = self.bin / name
        path.write_text(f'#!/bin/bash\necho "$@" >> "{self.calls[name]}"\n{body}')
        path.chmod(0o755)

    def env(self, **kw):
        e = {"PATH": os.environ["PATH"], "HOME": str(self.home),
             "LAUNCHCTL": str(self.bin / "launchctl"), "OSASCRIPT": str(self.bin / "osascript"),
             "PYTHON": str(self.bin / "python"), "LA_DIR": str(self.la),
             "STATE_DIR": str(self.state), "LOG_DIR": str(self.logs), "NOW": str(T0),
             "BOOTSTRAP_RETRY_SLEEP": "0"}
        e.update(self.extra)
        e.update({k: str(v) for k, v in kw.items()})
        return e

    def run(self, script, *args, **kw):
        return subprocess.run(["bash", str(SCRIPTS / script), *args], env=self.env(**kw),
                              capture_output=True, text=True, timeout=60)

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

@pytest.mark.parametrize("label", [SYNC, WATCHDOG])
@pytest.mark.skipif(shutil.which("plutil") is None, reason="plutil not available")
def test_plist_templates_lint(label):
    tpl = SKILL / "launchd" / f"{label}.plist.template"
    r = subprocess.run(["plutil", "-lint", str(tpl)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("label", [SYNC, WATCHDOG])
def test_plist_templates_have_no_keepalive_and_use_home_placeholder(label):
    text = (SKILL / "launchd" / f"{label}.plist.template").read_text()
    assert "KeepAlive" not in text
    assert f"<string>{label}</string>" in text
    assert "__SCRIPTS__/" in text and ".claude" not in text
    assert ("RunAtLoad" in text) == (label == WATCHDOG)


def test_skill_frontmatter_name_matches_directory():
    text = (SKILL / "SKILL.md").read_text()
    m = re.match(r"---\nname: (.+)\n", text)
    assert m and m.group(1).strip() == SKILL.name == "plan-week"
