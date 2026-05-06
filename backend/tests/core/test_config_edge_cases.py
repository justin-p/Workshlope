"""Branch coverage for Settings / CORS helpers."""

import pytest

from app.core.config import Settings, parse_cors


def test_parse_cors_rejects_non_sequence_string() -> None:
    with pytest.raises(ValueError):
        parse_cors(42)  # type: ignore[arg-type]


def test_settings_raises_on_default_password_in_production() -> None:
    with pytest.raises(ValueError, match="changethis"):
        Settings.model_validate(
            {
                "PROJECT_NAME": "proj",
                "POSTGRES_SERVER": "db",
                "POSTGRES_USER": "u",
                "FIRST_SUPERUSER": "a@example.com",
                "FIRST_SUPERUSER_PASSWORD": "changethis",
                "ENVIRONMENT": "production",
            }
        )


def test_settings_raises_on_default_postgres_password_non_local() -> None:
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        Settings.model_validate(
            {
                "PROJECT_NAME": "proj",
                "POSTGRES_SERVER": "db",
                "POSTGRES_USER": "u",
                "POSTGRES_PASSWORD": "changethis",
                "FIRST_SUPERUSER": "a@example.com",
                "FIRST_SUPERUSER_PASSWORD": "something-else-ok",
                "SECRET_KEY": "x" * 32,
                "ENVIRONMENT": "staging",
            }
        )


def test_settings_parses_backend_cors_origins_string_csv() -> None:
    s = Settings.model_validate(
        {
            "PROJECT_NAME": "proj",
            "POSTGRES_SERVER": "db",
            "POSTGRES_USER": "u",
            "FIRST_SUPERUSER": "a@example.com",
            "FIRST_SUPERUSER_PASSWORD": "pw",
            "BACKEND_CORS_ORIGINS": "http://a.com, https://b.com",
        }
    )
    assert isinstance(s.BACKEND_CORS_ORIGINS, list)
    cors_strs = [str(u).rstrip("/") for u in s.BACKEND_CORS_ORIGINS]
    assert "http://a.com" in cors_strs


def test_settings_parses_backend_cors_origins_json_list() -> None:
    """Exercises parse_cors isinstance list | str branch (list path)."""
    s = Settings.model_validate(
        {
            "PROJECT_NAME": "proj",
            "POSTGRES_SERVER": "db",
            "POSTGRES_USER": "u",
            "FIRST_SUPERUSER": "a@example.com",
            "FIRST_SUPERUSER_PASSWORD": "pw",
            "BACKEND_CORS_ORIGINS": ["http://c.com"],
        }
    )
    assert len(s.BACKEND_CORS_ORIGINS) == 1
