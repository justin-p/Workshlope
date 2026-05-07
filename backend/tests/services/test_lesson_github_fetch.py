"""lesson_github_fetch Contents API traversal (mocked httpx)."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from app.services.lesson_github_fetch import (
    GithubContentsFetchError,
    fetch_lesson_repo_path_map_from_github,
    parse_full_name,
)


def test_parse_full_name_strips_owner_repo() -> None:
    assert parse_full_name("  acme/widget  ") == ("acme", "widget")


@pytest.mark.parametrize(
    "raw",
    ["", "/", "bare", "//", "/onlyright", "onlyleft/"],
)
def test_parse_full_name_invalid(raw: str) -> None:
    with pytest.raises(GithubContentsFetchError, match="full_name must be owner/repo"):
        parse_full_name(raw)


def _blob_payload(text: str) -> dict[str, object]:
    b64 = base64.b64encode(text.encode()).decode()
    return {"encoding": "base64", "content": b64 + "\n"}


def _json_response(code: int, payload: object) -> MagicMock:
    r = MagicMock()
    r.status_code = code
    r.json.return_value = payload
    return r


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_reads_default_branch_then_lessons(mock_client_cls: MagicMock) -> None:
    manifest = """version: 1
lesson:
  slug: demo
  title: Demo
parts:
  - slug: one
    title: One
    path: one.md
"""
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm

    mock_inner.get.side_effect = [
        _json_response(200, {"default_branch": "develop"}),
        _json_response(200, [{"type": "dir", "path": "lessons/demo"}]),
        _json_response(200, _blob_payload(manifest)),
        _json_response(200, _blob_payload("# One")),
    ]

    pmap, ref = fetch_lesson_repo_path_map_from_github(
        token="ghs_test",
        full_name="o/r",
        default_branch=None,
    )
    assert ref == "develop"
    assert pmap["lessons/demo/lesson.manifest.yaml"].strip().startswith("version:")
    assert pmap["lessons/demo/one.md"] == "# One"


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_with_explicit_branch_skips_repo_meta(mock_client_cls: MagicMock) -> None:
    manifest = """version: 1
lesson:
  slug: demo
  title: Demo
parts:
  - slug: one
    title: One
    path: one.md
"""
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm

    mock_inner.get.side_effect = [
        _json_response(200, [{"type": "dir", "path": "lessons/x"}]),
        _json_response(200, _blob_payload(manifest)),
        _json_response(200, _blob_payload("# x")),
    ]

    _, ref = fetch_lesson_repo_path_map_from_github(
        token="t",
        full_name="o/r",
        default_branch="main",
    )
    assert ref == "main"
    assert mock_inner.get.call_count == 3


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_repo_meta_not_dict(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [_json_response(200, "weird")]

    with pytest.raises(GithubContentsFetchError, match="metadata JSON"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch=None
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_repo_meta_http_error(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [_json_response(401, {})]

    with pytest.raises(GithubContentsFetchError, match="metadata"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch=None
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_lessons_list_http_error_not_404(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [
        _json_response(200, {"default_branch": "main"}),
        _json_response(500, {}),
    ]

    with pytest.raises(GithubContentsFetchError, match="Could not list lessons"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch=None
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_lessons_directory_missing(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [
        _json_response(200, {"default_branch": "main"}),
        _json_response(404, {}),
    ]

    with pytest.raises(GithubContentsFetchError, match="missing lessons/"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch=None
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_lessons_list_not_array(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [
        _json_response(200, {"default_branch": "main"}),
        _json_response(200, {}),
    ]

    with pytest.raises(GithubContentsFetchError, match="listing shape"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch=None
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_skips_non_dirs_and_empty_map(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [
        _json_response(
            200,
            [
                {"type": "file", "path": "lessons/readme.md"},
                {"type": "dir"},
            ],
        ),
    ]

    with pytest.raises(GithubContentsFetchError, match="No lesson manifests"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch="main"
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_file_non_200(mock_client_cls: MagicMock) -> None:
    manifest = """version: 1
lesson:
  slug: demo
  title: Demo
parts:
  - slug: one
    title: One
    path: one.md
"""
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [
        _json_response(200, [{"type": "dir", "path": "lessons/demo"}]),
        _json_response(200, _blob_payload(manifest)),
        _json_response(500, {}),
    ]

    with pytest.raises(GithubContentsFetchError, match="Failed to read"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch="main"
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_file_payload_not_dict(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [
        _json_response(200, [{"type": "dir", "path": "lessons/demo"}]),
        _json_response(200, []),
    ]

    with pytest.raises(GithubContentsFetchError, match="Unexpected GitHub contents"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch="main"
        )


@patch("app.services.lesson_github_fetch.httpx.Client")
def test_fetch_blob_bad_encoding(mock_client_cls: MagicMock) -> None:
    mock_inner = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = mock_inner
    cm.__exit__.return_value = None
    mock_client_cls.return_value = cm
    mock_inner.get.side_effect = [
        _json_response(200, [{"type": "dir", "path": "lessons/demo"}]),
        _json_response(200, {"encoding": "none", "content": "zzz"}),
    ]

    with pytest.raises(GithubContentsFetchError, match="encoding"):
        fetch_lesson_repo_path_map_from_github(
            token="t", full_name="o/r", default_branch="main"
        )
