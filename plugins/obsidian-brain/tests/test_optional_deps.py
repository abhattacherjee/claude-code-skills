"""Tests for check_optional_deps() and the Phase 2 optional-deps config fields."""

import json

import pytest

import obsidian_utils


class TestCheckOptionalDeps:
    def test_reports_numpy_and_scipy_status(self):
        result = obsidian_utils.check_optional_deps()
        assert set(result.keys()) == {"numpy", "scipy"}
        for v in result.values():
            assert isinstance(v, bool)

    def test_missing_package_reports_false(self, monkeypatch):
        # Mock importlib.import_module at the source (obsidian_utils imports
        # it lazily inside check_optional_deps). We patch the importlib
        # module's import_module function to raise ImportError for the
        # target packages.
        import importlib as _importlib

        real_import_module = _importlib.import_module

        def fake_import_module(name, *args, **kwargs):
            if name in {"numpy", "scipy"}:
                raise ImportError(f"mocked ImportError for {name}")
            return real_import_module(name, *args, **kwargs)

        monkeypatch.setattr(_importlib, "import_module", fake_import_module)
        result = obsidian_utils.check_optional_deps()
        assert result == {"numpy": False, "scipy": False}

    def test_non_import_error_reports_false(self, monkeypatch):
        # Compiled optional deps (numpy/scipy wheels) can raise OSError when
        # their shared libraries are missing, ValueError on ABI mismatch, or
        # RuntimeError for other binary incompat. These must be treated as
        # "unavailable" rather than bubbling out of setup.
        import importlib as _importlib

        real_import_module = _importlib.import_module

        def fake_import_module(name, *args, **kwargs):
            if name == "numpy":
                raise OSError("libopenblas.0.dylib not loaded")
            if name == "scipy":
                raise ValueError("numpy.dtype size changed, binary incompat")
            return real_import_module(name, *args, **kwargs)

        monkeypatch.setattr(_importlib, "import_module", fake_import_module)
        result = obsidian_utils.check_optional_deps()
        assert result == {"numpy": False, "scipy": False}


class TestConfigDefaults:
    def test_optional_deps_fields_present_in_defaults(self):
        defaults = obsidian_utils._DEFAULTS
        assert defaults.get("optional_deps_prompted") is False
        assert defaults.get("optional_deps_declined") == []

    def test_load_config_fills_defaults_when_missing(self, tmp_path, monkeypatch):
        cfg = {"vault_path": "/tmp/v"}
        cfg_path = tmp_path / "obsidian-brain-config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(obsidian_utils, "_CONFIG_PATH", cfg_path)
        monkeypatch.setattr(
            obsidian_utils, "_get_session_id_fast", lambda: "test-session-id",
        )
        obsidian_utils.cache_set("test-session-id", "config", None)

        loaded = obsidian_utils.load_config()
        assert loaded["optional_deps_prompted"] is False
        assert loaded["optional_deps_declined"] == []

    def test_mutating_list_default_does_not_leak_across_loads(
        self, tmp_path, monkeypatch
    ):
        """Mutating config['optional_deps_declined'] must not leak into _DEFAULTS.

        Regression: dict(_DEFAULTS) is a shallow copy, so the same list
        object was shared across every load_config() return value and the
        _DEFAULTS module attribute. An in-place .append() in one caller
        would silently surface in the next caller's "default".
        """
        cfg = {"vault_path": "/tmp/v"}
        cfg_path = tmp_path / "obsidian-brain-config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr(obsidian_utils, "_CONFIG_PATH", cfg_path)
        monkeypatch.setattr(
            obsidian_utils, "_get_session_id_fast", lambda: "leak-test-session",
        )
        obsidian_utils.cache_set("leak-test-session", "config", None)

        first = obsidian_utils.load_config()
        first["optional_deps_declined"].append("poisoned-entry")

        # Bust the cache so the second call rebuilds from _DEFAULTS + disk.
        obsidian_utils.cache_set("leak-test-session", "config", None)
        second = obsidian_utils.load_config()

        assert second["optional_deps_declined"] == [], (
            "list default leaked across load_config() calls — "
            f"got {second['optional_deps_declined']!r}, _DEFAULTS "
            "is being shared (shallow copy regressed)"
        )
        assert obsidian_utils._DEFAULTS["optional_deps_declined"] == [], (
            "mutation from load_config return value leaked into _DEFAULTS"
        )
