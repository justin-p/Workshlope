"""lesson_markdown_pipeline: raw GitHub URL rewrite + safe HTML rendering."""

from app.services.lesson_markdown_pipeline import (
    lesson_markdown_to_safe_html,
    resolved_repo_path_for_asset,
    rewrite_relative_asset_urls,
    transform_markdown_outside_code_fences,
)


def test_rewrite_relative_markdown_link_with_custom_resolver() -> None:
    md = "See [diagram](./diagram.png)."
    got = rewrite_relative_asset_urls(
        md,
        part_repo_path="lessons/a/part.md",
        rewrite_repo_relative_path=lambda p: f"/asset?path={p}",
    )
    assert got == "See [diagram](/asset?path=lessons/a/diagram.png)."


def test_rewrite_preserves_https_and_mailto() -> None:
    md = "[u](mailto:a@b.com) [g](https://ex.com/z)"
    got = rewrite_relative_asset_urls(
        md,
        part_repo_path="lessons/a/part.md",
        rewrite_repo_relative_path=lambda p: f"/asset?path={p}",
    )
    assert got == md


def test_rewrite_root_relative_slash_paths_from_repo_root() -> None:
    md = "[a](/README.md)"
    got = rewrite_relative_asset_urls(
        md,
        part_repo_path="lessons/a/part.md",
        rewrite_repo_relative_path=lambda p: f"/asset?path={p}",
    )
    assert got == "[a](/asset?path=README.md)"


def test_rewrite_inside_code_fence_untouched() -> None:
    md = "```text\n![](./in-fence.png)\n```"
    got = rewrite_relative_asset_urls(
        md,
        part_repo_path="lessons/a/part.md",
        rewrite_repo_relative_path=lambda p: f"/asset?path={p}",
    )
    assert got == md


def test_rewrite_optional_link_title_kept() -> None:
    md = '[x](./a.png "t")'
    got = rewrite_relative_asset_urls(
        md,
        part_repo_path="lessons/a/part.md",
        rewrite_repo_relative_path=lambda p: f"/asset?path={p}",
    )
    expected = '[x](/asset?path=lessons/a/a.png "t")'
    assert got == expected


def test_traversal_relative_link_raises() -> None:
    md = "[x](../../../../etc/passwd)"
    got = rewrite_relative_asset_urls(
        md,
        part_repo_path="lessons/a/part.md",
        rewrite_repo_relative_path=lambda p: f"/asset?path={p}",
    )
    assert got == md


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
