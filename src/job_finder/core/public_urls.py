"""Shared validation for URLs that must target the public web."""

from __future__ import annotations

import ipaddress
import urllib.request
from urllib.parse import urlsplit


def validate_public_http_url(value: str, path: str) -> None:
    """Reject non-HTTP, credential-bearing, and literal non-public network targets."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{path} must be an absolute HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{path} must not contain credentials")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(f"{path} must target a public host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError(f"{path} must target a public host")


class PublicUrlRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects to credential-bearing or literal non-public targets."""

    def redirect_request(  # type: ignore[no-untyped-def]
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        validate_public_http_url(newurl, "redirect target")
        return super().redirect_request(req, fp, code, msg, headers, newurl)
