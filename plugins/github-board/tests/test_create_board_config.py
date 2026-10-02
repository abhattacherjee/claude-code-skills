"""create-board takes its template from the config; nothing names the author's board (#146)."""
import json
import os
import subprocess
import sys

from gbtest import SKILLS_DIR, TEST_CFG, cfg_copy, gh_calls, install_fake_gh, load_lib, write_config

SCRIPTS = SKILLS_DIR / "create-board" / "scripts"
PLUGIN = SKILLS_DIR.parent


def run(tmp_path, script, *args, stdin=None):
    log = tmp_path / "gh.log"
    env = dict(os.environ, GB_PYTHON=sys.executable, **install_fake_gh(tmp_path / "bin", [], log))
    r = subprocess.run(["bash", str(SCRIPTS / script), *args], input=stdin, env=env,
                       capture_output=True, text=True, timeout=60)
    return r, gh_calls(log)


def test_audit_without_config_or_flags_asks_for_init(tmp_path):
    r, calls = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all")
    assert r.returncode == 2 and "create-board init" in r.stderr
    assert calls == []


def test_audit_reads_the_template_from_the_config(tmp_path, gb_config):
    r, _ = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all")
    assert r.returncode == 2           # the fake gh fails the snapshot
    assert "Could not snapshot template octo-user/31" in r.stderr


def test_audit_flags_win_over_the_config(tmp_path, gb_config):
    r, _ = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all",
               "--template-owner", "other-owner", "--template", "7")
    assert "Could not snapshot template other-owner/7" in r.stderr


def test_audit_with_config_but_no_create_board_section_asks_for_init(tmp_path):
    c = cfg_copy(); del c["create_board"]
    write_config(tmp_path / "xdg-config", c)
    r, calls = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all")
    assert r.returncode == 2 and "create-board init" in r.stderr and calls == []


def test_init_config_adds_the_section_to_a_plan_week_config(tmp_path):
    c = cfg_copy(); del c["create_board"]
    path = write_config(tmp_path / "xdg-config", c)
    r, calls = run(tmp_path, "init-config.sh",
                   stdin=json.dumps({"create_board": {"template_owner": "octo-org", "template_number": 4}}))
    assert r.returncode == 0, r.stderr
    written = json.loads(path.read_text())
    assert written["create_board"] == {"template_owner": "octo-org", "template_number": 4}
    assert written["plan_week"] == TEST_CFG["plan_week"] and calls == []


def test_init_config_refuses_a_different_template_without_force(tmp_path, gb_config):
    new = json.dumps({"create_board": {"template_owner": "octo-org", "template_number": 4}})
    r, _ = run(tmp_path, "init-config.sh", stdin=new)
    assert r.returncode == 3
    r, _ = run(tmp_path, "init-config.sh", "--force", stdin=new)
    assert r.returncode == 0


def test_init_config_first_run_needs_an_owner(tmp_path):
    body = {"create_board": {"template_owner": "octo-org", "template_number": 4}}
    r, _ = run(tmp_path, "init-config.sh", stdin=json.dumps(body))
    assert r.returncode == 2 and "missing required key owner" in r.stderr
    body["owner"] = "octo-user"
    r, _ = run(tmp_path, "init-config.sh", stdin=json.dumps(body))
    assert r.returncode == 0
    assert load_lib().load(require=("create_board",))["create_board"]["template_number"] == 4


def test_init_config_show(tmp_path, gb_config):
    r, _ = run(tmp_path, "init-config.sh", "--show")
    assert r.returncode == 0 and json.loads(r.stdout) == TEST_CFG


def test_init_config_show_without_config_exits_4(tmp_path):
    assert run(tmp_path, "init-config.sh", "--show")[0].returncode == 4


def test_init_config_help_and_bad_argument(tmp_path):
    assert run(tmp_path, "init-config.sh", "--help")[0].returncode == 0
    assert run(tmp_path, "init-config.sh", "--nope")[0].returncode == 2


def test_skill_and_agents_name_no_default_template():
    text = (SKILLS_DIR / "create-board" / "SKILL.md").read_text()
    assert "#31" not in text and "`31`" not in text
    assert "## Mode: init" in text and "init-config.sh" in text
    inspector = (PLUGIN / "agents" / "template-inspector.md").read_text()
    assert "(default `" not in inspector


def test_init_config_rejects_extra_arguments(tmp_path, gb_config):
    for args in (("--force", "--nope"), ("--show", "extra")):
        r, _ = run(tmp_path, "init-config.sh", *args, stdin="{}")
        assert r.returncode == 2, (args, r.stderr)


def test_audit_with_only_one_template_flag_and_no_config_asks_for_init(tmp_path):
    r, calls = run(tmp_path, "audit-board.sh", "--owner", "octo-user", "--all", "--template", "7")
    assert r.returncode == 2 and "create-board init" in r.stderr and calls == []
