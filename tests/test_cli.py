from testing.cli import get_message


def test_get_message_returns_default_greeting():
    assert get_message() == "Hello from testing!"
