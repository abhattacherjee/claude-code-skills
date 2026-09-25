#!/usr/bin/env python3
"""Stand-in for the `codex` CLI, used by the codex-review, ensure-codex and
pick-adversary tests. No network, no model, no real login.

codex-review runs codex with only PATH, HOME and CODEX_HOME in its environment,
so the stub is driven by files under $HOME (always a temp dir in tests):
  $HOME/codex-stub.json   what to do (below); a missing file means defaults
  $HOME/codex-stub.log    one JSON line per call, appended

State keys:
  version              what `codex --version` prints (default "codex-cli 0.155.1")
  login                exit code of `codex login status` (default 0); a message goes to stderr
  login_stdout         text `codex login status` prints on stdout (default: nothing)
  load_project_config  true: act like a Codex that loads <repo>/.codex/config.toml; a
                       `model = "..."` line there makes exec fail with "unknown model ..."
  ignore_doc_override  true: act like a Codex that reads <repo>/AGENTS.md even when
                       `-c project_doc_max_bytes=0` is passed
  load_repo_skills     true: act like a Codex that loads <repo>/.agents/skills; on a
                       canary run, a CANARY-SKILL-<hex> token in any SKILL.md there
                       becomes a finding title
  load_repo_mcp        true: act like a Codex that starts the servers in <repo>/.mcp.json;
                       each server's command runs (with its args) before exec answers
  canary_answer        how a canary run answers when nothing leaked: "findings" (default,
                       an empty findings list), "none" (exit 0, write no -o file), or
                       "stdout_token" (print the AGENTS.md token on stdout only, and
                       write an empty findings list)
  exec                 list of actions, one per review `codex exec` call; the last repeats:
                         out          JSON value written to the -o file; a string is written as is
                         exit         exit code (default 0)
                         stderr       text printed on stderr
                         sleep        seconds to sleep before answering
                         spawn_child  true: start `sleep 60` and write its pid to $HOME/child.pid
                         delete       a path to delete before answering

<repo> is the -C argument. An isolation canary run is recognised by a
CANARY-<hex> token in <repo>/AGENTS.md. It never uses the exec list: the stub
answers with no findings when AGENTS.md is blocked, and with one finding titled
with the token when it is not.

A `login status` log line records argv and the environment's key names.
Each exec log line records argv, the environment's key names, CODEX_HOME, the
working directory, all of stdin, the --output-schema file's JSON, and whether
it was a canary run. A canary line also records the entries of <repo>/.git/hooks
(git_hooks) and the text of <repo>/.git/HEAD (git_head).
"""
import json
import os
import re
import subprocess
import sys
import time

HOME = os.environ.get("HOME", "")
STATE = os.path.join(HOME, "codex-stub.json")
LOG = os.path.join(HOME, "codex-stub.log")
CANARY_RE = re.compile(r"CANARY-[0-9a-f]+")
MODEL_RE = re.compile(r'^model\s*=\s*"([^"]+)"', re.M)
SKILL_RE = re.compile(r"CANARY-SKILL-[0-9a-f]+")


def load():
    if os.path.exists(STATE):
        with open(STATE) as fh:
            return json.load(fh)
    return {}


def save(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def log(entry):
    with open(LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except (OSError, TypeError):
        return ""


def arg_after(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


def write_out(argv, body):
    out = arg_after(argv, "-o")
    if out:
        with open(out, "w") as fh:
            fh.write(body if isinstance(body, str) else json.dumps(body))


def repo_skill_token(repo):
    root = os.path.join(repo, ".agents", "skills")
    if not os.path.isdir(root):
        return None
    for name in sorted(os.listdir(root)):
        match = SKILL_RE.search(read(os.path.join(root, name, "SKILL.md")))
        if match:
            return match.group(0)
    return None


def start_repo_mcp(repo):
    try:
        servers = json.loads(read(os.path.join(repo, ".mcp.json")) or "{}").get("mcpServers", {})
    except ValueError:
        return
    for server in servers.values():
        subprocess.run([server["command"]] + list(server.get("args", [])),
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30)


def run_exec(argv, state):
    repo = arg_after(argv, "-C") or os.getcwd()
    canary = CANARY_RE.search(read(os.path.join(repo, "AGENTS.md")))
    stdin_text = sys.stdin.read()
    schema_text = read(arg_after(argv, "--output-schema"))
    entry = {"argv": argv, "env": sorted(os.environ), "codex_home": os.environ.get("CODEX_HOME"),
             "cwd": os.getcwd(), "stdin": stdin_text,
             "schema": json.loads(schema_text) if schema_text else None, "canary": bool(canary)}
    if canary:
        hooks = os.path.join(repo, ".git", "hooks")
        entry["git_hooks"] = sorted(os.listdir(hooks)) if os.path.isdir(hooks) else []
        entry["git_head"] = read(os.path.join(repo, ".git", "HEAD"))
    log(entry)
    if state.get("load_project_config"):
        model = MODEL_RE.search(read(os.path.join(repo, ".codex", "config.toml")))
        if model:
            print("error: unknown model " + model.group(1), file=sys.stderr)
            return 1
    if state.get("load_repo_mcp"):
        start_repo_mcp(repo)
    if canary:
        skill = repo_skill_token(repo) if state.get("load_repo_skills") else None
        if skill:
            write_out(argv, {"findings": [{
                "path": "a.py", "line": 2, "severity": "minor", "category": "bug",
                "title": skill, "rationale": "followed .agents/skills"}]})
            return 0
        blocked = "project_doc_max_bytes=0" in argv and not state.get("ignore_doc_override")
        if blocked and state.get("canary_answer") == "none":
            return 0
        if blocked and state.get("canary_answer") == "stdout_token":
            print(canary.group(0))
            write_out(argv, {"findings": []})
            return 0
        findings = [] if blocked else [{
            "path": "a.py", "line": 2, "severity": "minor", "category": "bug",
            "title": canary.group(0), "rationale": "followed AGENTS.md"}]
        write_out(argv, {"findings": findings})
        return 0
    actions = state.get("exec") or [{"out": {"findings": []}}]
    n = state.get("exec_calls", 0)
    action = actions[min(n, len(actions) - 1)]
    state["exec_calls"] = n + 1
    save(state)
    if action.get("delete") and os.path.exists(action["delete"]):
        os.remove(action["delete"])
    if action.get("spawn_child"):
        child = subprocess.Popen(["sleep", "60"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        with open(os.path.join(HOME, "child.pid"), "w") as fh:
            fh.write(str(child.pid))
    if action.get("sleep"):
        time.sleep(action["sleep"])
    if action.get("stderr"):
        print(action["stderr"], file=sys.stderr)
    if "out" in action:
        write_out(argv, action["out"])
    return action.get("exit", 0)


def main(argv):
    state = load()
    if argv[:1] in (["--version"], ["-V"]):
        log({"argv": argv})
        print(state.get("version", "codex-cli 0.155.1"))
        return 0
    if argv[:2] == ["login", "status"]:
        log({"argv": argv, "env": sorted(os.environ)})
        code = state.get("login", 0)
        if state.get("login_stdout"):
            print(state["login_stdout"])
        print("Logged in using ChatGPT" if code == 0 else "Not logged in", file=sys.stderr)
        return code
    if argv[:1] == ["exec"]:
        return run_exec(argv, state)
    log({"argv": argv})
    print("codex stub: unsupported call: " + " ".join(argv), file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
