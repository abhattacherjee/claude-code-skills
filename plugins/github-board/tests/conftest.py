import pytest

from gbtest import TEST_CFG, write_config


@pytest.fixture(autouse=True)
def _isolated_xdg(tmp_path, monkeypatch):
    """No test reads or writes the real ~/.config, ~/.cache or ~/.local/share."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("GITHUB_BOARD_HOME", str(tmp_path / "share" / "github-board"))
    monkeypatch.setenv("GITHUB_BOARD_LINK", str(tmp_path / "share" / "github-board" / "current"))


@pytest.fixture
def gb_config(tmp_path):
    """TEST_CFG written to the isolated config dir. Returns the file path."""
    return write_config(tmp_path / "xdg-config", TEST_CFG)
