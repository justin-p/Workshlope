"""lesson_markdown_pipeline: raw GitHub URL rewrite + safe HTML rendering."""

import pytest

from app.services.lesson_markdown_pipeline import (
    RelativeAssetRewriteError,
    lesson_markdown_to_safe_html,
    resolved_repo_path_for_asset,
    sync_markdown_rewrite_relative_assets,
    transform_markdown_outside_code_fences,
)


def test_sync_rewrite_relative_markdown_link_to_raw_github() -> None:
    md = "See [diagram](./diagram.png)."
    got = sync_markdown_rewrite_relative_assets(
        md,
        part_repo_path="lessons/a/part.md",
        github_full_name="org/acme-repo",
        default_branch="main",
    )
    assert (
        got
        == "See [diagram](https://raw.githubusercontent.com/org/acme-repo/main/lessons/a/diagram.png)."
    )


def test_sync_rewrite_preserves_https_and_mailto() -> None:
    md = "[u](mailto:a@b.com) [g](https://ex.com/z)"
    got = sync_markdown_rewrite_relative_assets(
        md,
        part_repo_path="lessons/a/part.md",
        github_full_name="org/acme-repo",
        default_branch="main",
    )
    assert got == md


def test_sync_rewrite_root_relative_slash_paths_from_repo_root() -> None:
    md = "[a](/README.md)"
    got = sync_markdown_rewrite_relative_assets(
        md,
        part_repo_path="lessons/a/part.md",
        github_full_name="org/acme-repo",
        default_branch="main",
    )
    assert got == "[a](https://raw.githubusercontent.com/org/acme-repo/main/README.md)"


def test_sync_rewrite_inside_code_fence_untouched() -> None:
    md = "```text\n![](./in-fence.png)\n```"
    got = sync_markdown_rewrite_relative_assets(
        md,
        part_repo_path="lessons/a/part.md",
        github_full_name="org/acme-repo",
        default_branch="main",
    )
    assert got == md


def test_sync_rewrite_optional_link_title_kept() -> None:
    md = '[x](./a.png "t")'
    got = sync_markdown_rewrite_relative_assets(
        md,
        part_repo_path="lessons/a/part.md",
        github_full_name="org/acme-repo",
        default_branch="main",
    )
    expected = (
        '[x](https://raw.githubusercontent.com/org/acme-repo/main/lessons/a/a.png "t")'
    )
    assert got == expected


def test_invalid_full_name_raises() -> None:
    with pytest.raises(RelativeAssetRewriteError):
        sync_markdown_rewrite_relative_assets(
            "x",
            part_repo_path="a.md",
            github_full_name="bad",
            default_branch="main",
        )


def test_traversal_relative_link_raises() -> None:
    md = "[x](../../../../etc/passwd)"
    with pytest.raises(RelativeAssetRewriteError, match="Unsafe"):
        sync_markdown_rewrite_relative_assets(
            md,
            part_repo_path="lessons/a/part.md",
            github_full_name="org/acme-repo",
            default_branch="main",
        )


def test_resolved_repo_path_for_asset() -> None:
    assert (
        resolved_repo_path_for_asset(
            part_repo_path="lessons/a/part.md",
            raw_href="./z.png",
        )
        == "lessons/a/z.png"
    )


def test_transform_markdown_outside_code_fences_skips_fence_bodies() -> None:
    md = "OUT1\n```\nINNER\n```\nOUT2"
    seen: list[str] = []

    def spy(seg: str) -> str:
        seen.append(seg)
        return seg

    transform_markdown_outside_code_fences(md, spy)
    inner_hits = sum(1 for s in seen if "INNER" in s)
    assert inner_hits == 0
    assert any("OUT1" in s for s in seen) and any("OUT2" in s for s in seen)


def test_lesson_markdown_to_safe_html_escapes_raw_tags() -> None:
    html = lesson_markdown_to_safe_html("<script>alert(1)</script>\nhello")
    assert "<script>" not in html
    assert "hello" in html


def test_lesson_markdown_to_safe_html_allows_https_links() -> None:
    html = lesson_markdown_to_safe_html("[x](https://example.org/y)")
    assert 'href="https://example.org/y"' in html
