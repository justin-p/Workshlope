"""Smoke coverage for optional DB bootstrap CLI."""

from app import initial_data


def test_init_calls_init_db(caplog):
    """init() shells to init_db; safe to call when DB already seeded (fixture)."""
    caplog.set_level("INFO")

    initial_data.init()


def test_main_logs_and_runs(caplog):
    caplog.set_level("INFO")

    initial_data.main()

    assert any("Creating initial data" in r.message for r in caplog.records)
    assert any("Initial data created" in r.message for r in caplog.records)
