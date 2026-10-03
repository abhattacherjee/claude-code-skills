"""The security helpers are byte-identical in every copy the plugin ships (#158, C-004).

Three copies: install's references/statusline-command.sh, the script create's generator
emits (taken from a real generated script, so the test checks what ships), and
create's references/item-recipes.md. Every helper that appears in more than one copy must
match the others exactly.
"""
import re
import subprocess

import pytest

from sltest import GENERATE, REFERENCE, SKILLS

RECIPES = SKILLS / "create" / "references" / "item-recipes.md"
HELPERS = ["clean", "num", "_git", "unsafe_repo"]
COMMENT = "# kept identical by tests/test_helper_parity.py"


def extract(text: str, name: str):
    """The helper's definition: one line `name() { ...; }`, or `name() {` ... `}`."""
    m = re.search(rf"^{re.escape(name)}\(\) \{{.*\}}$", text, re.M)
    if m:
        return m.group(0)
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?\n\}}$", text, re.M | re.S)
    return m.group(0) if m else None


@pytest.fixture(scope="module")
def copies(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("parity")
    out = tmp / "generated.sh"
    r = subprocess.run(["bash", str(GENERATE), "--items", "model,git,git-sync,context-bar",
                        "--output", str(out)], capture_output=True, text=True,
                       env={"PATH": __import__("os").environ["PATH"], "HOME": str(tmp)})
    assert r.returncode == 0, r.stderr
    return {"install/references/statusline-command.sh": REFERENCE.read_text(),
            "generated script (create)": out.read_text(),
            "create/references/item-recipes.md": RECIPES.read_text()}


@pytest.mark.parametrize("name", HELPERS)
def test_helper_is_identical_in_every_copy(copies, name):
    found = {src: extract(text, name) for src, text in copies.items()}
    found = {src: body for src, body in found.items() if body is not None}
    assert len(found) >= 2, f"{name}: in fewer than two copies ({sorted(found)})"
    groups = {}
    for src, body in found.items():
        groups.setdefault(body, []).append(src)
    if len(groups) > 1:
        ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
        if len(ranked[0][1]) > 1:            # a majority copy: name the ones that differ
            odd = [s for body, srcs in ranked[1:] for s in srcs]
            pytest.fail(f"helper {name} differs in {', '.join(odd)} "
                        f"(the other copies agree: {', '.join(ranked[0][1])})")
        pytest.fail(f"helper {name} differs between {', '.join(found)}")


def test_core_helpers_are_in_all_three_copies(copies):
    for name in ("clean", "_git", "unsafe_repo"):
        for src, text in copies.items():
            assert extract(text, name), f"{name} missing from {src}"


def test_each_copy_points_at_this_test(copies):
    for src, text in copies.items():
        for name in HELPERS:
            body = extract(text, name)
            if body:
                before = text[:text.index(body)].rstrip("\n").splitlines()
                assert COMMENT in before[-6:], f"{src}: no '{COMMENT}' just above {name}"
