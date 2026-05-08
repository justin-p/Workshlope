"""Fetch lesson manifests and markdown parts from GitHub (Contents API)."""

from __future__ import annotations

import base64
from urllib.parse import quote

import httpx

from app.services.lesson_manifest import parse_lesson_manifest


class GithubContentsFetchError(RuntimeError):
    """Unable to read ``lessons/*/lesson.manifest.yaml`` or referenced ``.md`` files."""


_GITHUB_API_VERSION = "2022-11-28"


def parse_full_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split("/", maxsplit=1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise GithubContentsFetchError("full_name must be owner/repo")
    return parts[0], parts[1]


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }


def _encode_path_segments(path: str) -> str:
    return "/".join(quote(segment, safe="") for segment in path.split("/") if segment)


def _decode_contents_payload(data: dict[str, object]) -> str:
    if data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
        raise GithubContentsFetchError("Unexpected GitHub blob encoding")
    raw_b64 = str(data["content"]).replace("\n", "")
    return base64.b64decode(raw_b64).decode("utf-8")


def _fetch_file_text(
    *,
    client: httpx.Client,
    owner: str,
    repo: str,
    path: str,
    ref: str,
    headers: dict[str, str],
) -> str:
    encoded = _encode_path_segments(path)
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded}"
    response = client.get(url, params={"ref": ref}, headers=headers)
    if response.status_code != 200:
        raise GithubContentsFetchError(
            f"Failed to read {path!r}: HTTP {response.status_code}",
        )
    payload_body = response.json()
    if not isinstance(payload_body, dict):
        raise GithubContentsFetchError("Unexpected GitHub contents JSON")
    return _decode_contents_payload(payload_body)


def fetch_repo_file_bytes_from_github(
    *,
    token: str,
    full_name: str,
    ref: str,
    path: str,
) -> tuple[bytes, str | None]:
    """Fetch repository file bytes via GitHub Contents API using installation auth."""
    owner, repo = parse_full_name(full_name)
    encoded = _encode_path_segments(path)
    headers = {
        **_auth_headers(token),
        "Accept": "application/vnd.github.raw",
    }
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded}",
            params={"ref": ref},
            headers=headers,
        )
    if response.status_code != 200:
        raise GithubContentsFetchError(
            f"Failed to read binary asset {path!r}: HTTP {response.status_code}",
        )
    return response.content, response.headers.get("content-type")


def fetch_lesson_repo_path_map_from_github(
    *,
    token: str,
    full_name: str,
    default_branch: str | None = None,
) -> tuple[dict[str, str], str]:
    """List ``lessons/*`` directories, fetch each ``lesson.manifest.yaml`` and part files.

    Keys in the returned dict are repository-relative POSIX paths (slashes), matching
    :func:`app.services.lesson_repo_sync.sync_lesson_repo_from_path_map`.
    """
    owner, repo = parse_full_name(full_name)
    headers = _auth_headers(token)

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        ref = default_branch
        if not ref:
            meta_res = client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers,
            )
            if meta_res.status_code != 200:
                raise GithubContentsFetchError(
                    f"Failed to read repository metadata: HTTP {meta_res.status_code}",
                )
            meta = meta_res.json()
            if not isinstance(meta, dict):
                raise GithubContentsFetchError("Unexpected repository metadata JSON")
            ref = str(meta.get("default_branch") or "main")

        list_res = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{_encode_path_segments('lessons')}",
            params={"ref": ref},
            headers=headers,
        )
        if list_res.status_code == 404:
            raise GithubContentsFetchError(
                "Repository is missing lessons/ directory at repository root",
            )
        if list_res.status_code != 200:
            raise GithubContentsFetchError(
                f"Could not list lessons/: HTTP {list_res.status_code}",
            )
        listing = list_res.json()
        if not isinstance(listing, list):
            raise GithubContentsFetchError("Unexpected lessons/ listing shape")

        path_map: dict[str, str] = {}
        for entry in listing:
            if entry.get("type") != "dir":
                continue
            lesson_dir = entry.get("path")
            if not isinstance(lesson_dir, str) or not lesson_dir:
                continue
            manifest_rel = f"{lesson_dir}/lesson.manifest.yaml"
            manifest_text = _fetch_file_text(
                client=client,
                owner=owner,
                repo=repo,
                path=manifest_rel,
                ref=ref,
                headers=headers,
            )
            path_map[manifest_rel] = manifest_text
            manifest_model = parse_lesson_manifest(manifest_text)
            for part in manifest_model.parts:
                part_path = f"{lesson_dir}/{part.path}"
                path_map[part_path] = _fetch_file_text(
                    client=client,
                    owner=owner,
                    repo=repo,
                    path=part_path,
                    ref=ref,
                    headers=headers,
                )

        if not path_map:
            raise GithubContentsFetchError(
                "No lesson manifests were found under lessons/",
            )
        return path_map, ref
