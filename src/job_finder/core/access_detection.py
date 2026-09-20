"""Conservative detection of visible authentication and anti-automation pages."""

from __future__ import annotations

import re
from html import unescape


def extract_html_title(text: str) -> str | None:
    """Return a compact decoded HTML title when one is present."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if not title_match:
        return None
    return re.sub(r"\s+", " ", unescape(title_match.group(1))).strip()[:200] or None


def is_access_block_html(text: str, page_title: str | None = None) -> bool:
    """Detect an active challenge without matching dormant form configuration in scripts."""
    title = (page_title if page_title is not None else extract_html_title(text)) or ""
    title_markers = (
        "access denied",
        "attention required! | cloudflare",
        "captcha",
        "login required",
        "sign in to continue",
        "verify you are human",
    )
    if any(marker in title.lower() for marker in title_markers):
        return True

    visible_html = re.sub(
        r"<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    visible_text = unescape(re.sub(r"<[^>]+>", " ", visible_html))
    visible_text = re.sub(r"\s+", " ", visible_text).lower()
    visible_markers = (
        "access denied",
        "captcha challenge",
        "captcha verification",
        "complete the captcha",
        "login required",
        "sign in to continue",
        "verify you are human",
    )
    return any(marker in visible_text for marker in visible_markers)
