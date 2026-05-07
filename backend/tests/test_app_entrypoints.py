"""Coverage for app.main (Sentry gate) and initial_data __main__."""

import importlib
import runpy
from unittest.mock import MagicMock

import pytest
from pydantic import HttpUrl

import app.core.config as app_config


def test_main_initializes_sentry_when_dsn_set_and_not_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "SENTRY_DSN",
        HttpUrl("https://aaa@o0.ingest.example/1"),
        raising=False,
    )
    monkeypatch.setattr(app_config.settings, "ENVIRONMENT", "staging", raising=False)

    init_mock = MagicMock()
    monkeypatch.setattr("sentry_sdk.init", init_mock)

    import app.main as main_mod

    importlib.reload(main_mod)
    assert init_mock.called


def test_initial_data_module_main_block() -> None:
    runpy.run_module("app.initial_data", run_name="__main__")
