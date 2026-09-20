"""Tests for sanitized source-probe classification."""

from job_finder.core.source_probe import ProbeOutcome, classify_probe_body


def classify(body: bytes, *, expect_json: bool, content_type: str = "text/html"):
    return classify_probe_body(
        requested_url="https://jobs.example.com",
        final_url="https://jobs.example.com",
        status_code=200,
        content_type=content_type,
        body=body,
        expect_json_jobs=expect_json,
    )


def test_public_json_job_collection_is_counted() -> None:
    result = classify(b'{"jobs": [{"id": 1}, {"id": 2}]}', expect_json=True)

    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.job_count == 2


def test_json_list_is_supported_for_lever_style_payload() -> None:
    result = classify(b'[{"id": "one"}]', expect_json=True, content_type="application/json")

    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.job_count == 1


def test_login_or_captcha_page_is_not_healthy_html() -> None:
    result = classify(b"<html><title>Sign in</title>Login required</html>", expect_json=False)

    assert result.outcome is ProbeOutcome.ACCESS_BLOCK


def test_dormant_captcha_configuration_does_not_block_public_careers_page() -> None:
    result = classify(
        b"""
        <html>
          <title>Engineering jobs</title>
          <script>window.config = {"captchaEnabled": true, "useCaptcha": true};</script>
          <body><h1>Engineering and Product jobs</h1></body>
        </html>
        """,
        expect_json=False,
    )

    assert result.outcome is ProbeOutcome.SUCCESS


def test_html_instead_of_expected_json_is_invalid() -> None:
    result = classify(b"<html><title>Jobs</title></html>", expect_json=True)

    assert result.outcome is ProbeOutcome.INVALID_CONTENT


def test_public_html_title_is_sanitized() -> None:
    result = classify(b"<html><title>  Example\n Careers </title></html>", expect_json=False)

    assert result.outcome is ProbeOutcome.SUCCESS
    assert result.page_title == "Example Careers"
