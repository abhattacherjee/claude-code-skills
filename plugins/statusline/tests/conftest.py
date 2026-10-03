import pytest

from sltest import Env, find_bash32

BASH32 = find_bash32()


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture(params=["bash", "bash-3.2"])
def bash(request):
    """The PATH bash (bash 5 on Linux CI), and macOS's bash 3.2 where it exists."""
    if request.param == "bash":
        return "bash"
    if BASH32 is None:
        pytest.skip("bash 3.2 not on this host (macOS ships it as /bin/bash)")
    return BASH32
