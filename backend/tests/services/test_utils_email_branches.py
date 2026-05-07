"""send_email branching (TLS vs SSL vs password)."""

from unittest.mock import MagicMock

import pytest

from app import utils


def test_send_email_uses_ssl_when_tls_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocked_message = MagicMock()
    mocked_message.send = MagicMock(return_value={"ok": True})
    msg_factory = MagicMock(return_value=mocked_message)

    monkeypatch.setattr(utils.settings, "SMTP_HOST", "smtp.example.test", raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_TLS", False, raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_SSL", True, raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_PORT", 465, raising=False)
    monkeypatch.setattr(
        utils.settings, "EMAILS_FROM_EMAIL", "from@example.com", raising=False
    )
    monkeypatch.setattr(utils.settings, "EMAILS_FROM_NAME", "Proj", raising=False)

    monkeypatch.setattr(utils.emails, "Message", msg_factory)

    utils.send_email(
        email_to="to@example.com",
        subject="S",
        html_content="<p>hi</p>",
    )
    kw = mocked_message.send.call_args[1]["smtp"]
    assert kw["ssl"] is True
    assert "tls" not in kw


def test_send_email_adds_credentials_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocked_message = MagicMock()
    mocked_message.send = MagicMock(return_value={})
    msg_factory = MagicMock(return_value=mocked_message)

    monkeypatch.setattr(utils.settings, "SMTP_HOST", "smtp.example.test", raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_TLS", True, raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_SSL", False, raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_PORT", 587, raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_USER", "u", raising=False)
    monkeypatch.setattr(utils.settings, "SMTP_PASSWORD", "p", raising=False)
    monkeypatch.setattr(
        utils.settings, "EMAILS_FROM_EMAIL", "from@example.com", raising=False
    )

    monkeypatch.setattr(utils.emails, "Message", msg_factory)

    utils.send_email(
        email_to="to@example.com",
        subject="S",
        html_content="<p>hi</p>",
    )
    smtp_kw = mocked_message.send.call_args[1]["smtp"]
    assert smtp_kw["user"] == "u"
    assert smtp_kw["password"] == "p"


def test_generate_test_email_includes_subject() -> None:
    data = utils.generate_test_email(email_to="student@school.edu")
    assert "Test email" in data.subject
    assert "student@school.edu" in data.html_content
