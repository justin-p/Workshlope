"""Lesson markdown: render-time asset rewrites and safe HTML rendering helpers."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from pathlib import PurePosixPath

import nh3
from markdown_it import MarkdownIt

_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_IFRAME_BLOCK_RE = re.compile(r"<iframe\b[^>]*>.*?</iframe>", re.DOTALL | re.IGNORECASE)
# Captures markdown inline links/images: `(...)` body may include an optional quoted title.
_INLINE_LINK_RE = re.compile(r"(?P<prefix>!?\[[^\]]*\])\(\s*(?P<inside>[^\)]*?)\s*\)")
_HTML_URL_ATTR_RE = re.compile(
    r"(?P<attr>\b(?:src|href))\s*=\s*(?P<quote>[\"'])(?P<url>[^\"']+)(?P=quote)",
    re.IGNORECASE | re.MULTILINE,
)


class RelativeAssetRewriteError(ValueError):
    """Rejected relative asset URL in markdown (unsafe path)."""


def resolved_repo_path_for_asset(
    *,
    part_repo_path: str,
    raw_href: str,
) -> str:
    """Resolve a repository-relative markdown/HTML href against the part file directory."""
    href = raw_href.strip()
    parent = PurePosixPath(part_repo_path).parent.as_posix()
    base = "" if parent == "." else parent
    if href.startswith("/"):
        joined = posixpath.normpath(href.lstrip("/"))
    elif base == "":
        joined = posixpath.normpath(href)
    else:
        joined = posixpath.normpath(f"{base}/{href}")
    norm = posixpath.normpath(joined)
    if not norm or norm.startswith("../") or "/../" in f"/{norm}/":
        raise RelativeAssetRewriteError(
            f"Unsafe relative asset path in markdown: {raw_href!r}",
        )
    return norm


def _rewrite_target_url(
    raw: str,
    *,
    part_repo_path: str,
    rewrite_repo_relative_path: Callable[[str], str],
) -> str:
    u = raw.strip()
    lu = u.lower()
    if not u:
        return u
    if lu.startswith("javascript:"):
        return "#"
    if lu.startswith(("http://", "https://", "mailto:", "#", "data:")):
        return u
    if u.startswith("//"):
        return u
    try:
        resolved = resolved_repo_path_for_asset(
            part_repo_path=part_repo_path, raw_href=u
        )
    except RelativeAssetRewriteError:
        # Keep original markdown URL when normalization rejects it; do not fail render.
        return u
    return rewrite_repo_relative_path(resolved)


def transform_markdown_outside_code_fences(text: str, fn: Callable[[str], str]) -> str:
    """Apply ``fn`` only to spans outside ```fenced``` blocks."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        fence = text.find("```", i)
        if fence == -1:
            out.append(fn(text[i:]))
            break
        out.append(fn(text[i:fence]))
        close = text.find("```", fence + 3)
        if close == -1:
            out.append(text[fence:])
            break
        out.append(text[fence : close + 3])
        i = close + 3
    return "".join(out)


def _scrub_plain_markdown_segment(text: str) -> str:
    """Strip dangerous inline HTML payloads that could surprise a future Markdown renderer."""
    cleaned = text.replace("\x00", "")
    cleaned = _SCRIPT_BLOCK_RE.sub("", cleaned)
    cleaned = _IFRAME_BLOCK_RE.sub("", cleaned)
    return cleaned


def _split_inline_link_inside(inside: str) -> tuple[str, str]:
    """Split ``(...)`` payload into URL / path token and trailing title fragment."""
    raw = inside.strip()
    if not raw:
        return "", ""
    if raw.startswith("<"):
        gt = raw.find(">")
        if gt == -1:
            return raw, ""
        url = raw[1:gt].strip()
        remainder = raw[gt + 1 :].strip()
        return url, remainder
    head, sep, tail = raw.partition(" ")
    url = head.strip()
    remainder = tail.strip() if sep else ""
    return url, remainder


def _rewrite_plain_segment_urls(
    segment: str,
    *,
    part_repo_path: str,
    rewrite_repo_relative_path: Callable[[str], str],
) -> str:
    seg = _scrub_plain_markdown_segment(segment)

    def repl_link(match: re.Match[str]) -> str:
        prefix, inside = match.group("prefix"), match.group("inside")
        url_raw, remainder = _split_inline_link_inside(inside)
        new_url = _rewrite_target_url(
            url_raw,
            part_repo_path=part_repo_path,
            rewrite_repo_relative_path=rewrite_repo_relative_path,
        )
        spacer = " " if remainder else ""
        return f"{prefix}({new_url}{spacer}{remainder})".rstrip()

    seg_after_md = _INLINE_LINK_RE.sub(repl_link, seg)

    def repl_attr(match: re.Match[str]) -> str:
        attr, quote_mark, raw_url = (
            match.group("attr"),
            match.group(
                "quote",
            ),
            match.group("url"),
        )
        new_url = _rewrite_target_url(
            raw_url,
            part_repo_path=part_repo_path,
            rewrite_repo_relative_path=rewrite_repo_relative_path,
        )
        return f"{attr}={quote_mark}{new_url}{quote_mark}"

    return _HTML_URL_ATTR_RE.sub(repl_attr, seg_after_md)


def rewrite_relative_asset_urls(
    body_md: str,
    *,
    part_repo_path: str,
    rewrite_repo_relative_path: Callable[[str], str],
) -> str:
    """Rewrite relative markdown/HTML asset URLs via ``rewrite_repo_relative_path``."""
    return transform_markdown_outside_code_fences(
        body_md,
        lambda s: _rewrite_plain_segment_urls(
            s,
            part_repo_path=part_repo_path,
            rewrite_repo_relative_path=rewrite_repo_relative_path,
        ),
    )


def collect_relative_asset_repo_paths(
    body_md: str,
    *,
    part_repo_path: str,
) -> set[str]:
    """Collect repository-relative asset paths referenced by markdown/html URLs."""
    collected: set[str] = set()

    def _collect_path(repo_relative_path: str) -> str:
        collected.add(repo_relative_path)
        return repo_relative_path

    rewrite_relative_asset_urls(
        body_md,
        part_repo_path=part_repo_path,
        rewrite_repo_relative_path=_collect_path,
    )
    return collected


_SAFE_HTML_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "b",
        "i",
        "u",
        "ul",
        "ol",
        "li",
        "a",
        "code",
        "pre",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "img",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
    },
)

_SAFE_HTML_ATTRIBUTES = {
    "a": {"href", "title", "name"},
    "img": {"src", "alt", "title", "loading"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    # Fenced code uses class="language-…" for client-side syntax highlighting.
    "code": {"class"},
    "pre": {"class"},
}


def lesson_markdown_to_safe_html(markdown_source: str) -> str:
    """
    Render CommonMark subset to HTML and pass through nh3 allowlists.

    Raw HTML in the markdown source is disabled at the Markdown layer; nh3 adds a second pass.
    """
    md = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(["table"])
    raw_html = md.render(markdown_source)
    return nh3.clean(
        raw_html,
        tags=_SAFE_HTML_TAGS,
        attributes=_SAFE_HTML_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )
