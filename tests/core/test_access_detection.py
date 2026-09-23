"""Phase 10 access-page failure drills."""

from pathlib import Path

import pytest

from job_finder.core.access_detection import is_access_block_html


@pytest.mark.parametrize("fixture_name", ["captcha.html", "login.html"])
def test_visible_captcha_and_login_pages_are_access_blocks(fixture_name: str) -> None:
    text = (Path("tests/fixtures/shared") / fixture_name).read_text(encoding="utf-8")

    assert is_access_block_html(text) is True


def test_dormant_access_terms_inside_scripts_are_not_active_blocks() -> None:
    text = """
    <html><head><title>Public careers</title></head><body>
      <script>const settings = {captcha: true, loginRequired: true};</script>
      <main>Browse all public jobs</main>
    </body></html>
    """

    assert is_access_block_html(text) is False
