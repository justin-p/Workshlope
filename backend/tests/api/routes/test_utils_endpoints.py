"""Utility routes (health + test-email)."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from tests.utils.utils import get_superuser_token_headers


def test_utils_health_check_is_public(client: TestClient) -> None:
    r = client.get(f"{settings.API_V1_STR}/utils/health-check/")
    assert r.status_code == 200
    assert r.json() is True


def test_utils_test_email_requires_superuser_and_sends(
    client: TestClient,
) -> None:
    with (
        patch("app.api.routes.utils.send_email") as send_email,
        patch("app.api.routes.utils.generate_test_email") as gen,
    ):
        gen.return_value.subject = "S"
        gen.return_value.html_content = "<html/>"
        r = client.post(
            f"{settings.API_V1_STR}/utils/test-email/",
            headers=get_superuser_token_headers(client),
            params={"email_to": settings.FIRST_SUPERUSER},
        )
    assert r.status_code == 201
    assert r.json() == {"message": "Test email sent"}
    gen.assert_called_once()
    send_email.assert_called_once()
