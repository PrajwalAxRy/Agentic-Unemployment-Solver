"""Detect hosted ATS links in bounded public careers-page HTML."""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from job_finder.core.search_discovery import infer_adapter
from job_finder.core.source_probe import MAX_RESPONSE_BYTES, USER_AGENT


@dataclass(frozen=True, slots=True)
class AtsFingerprint:
    """One hosted ATS reference found in public page markup."""

    adapter_type: str
    adapter_parameters: Mapping[str, str]
    source_url: str
    list_endpoint: str
    listing_mode: str


@dataclass(frozen=True, slots=True)
class FingerprintProbeResult:
    """Sanitized fingerprint result; response HTML is never retained."""

    company_id: str
    requested_url: str
    final_url: str | None
    outcome: str
    status_code: int | None
    detail: str
    fingerprints: tuple[AtsFingerprint, ...]

    def as_json(self) -> dict[str, object]:
        data = asdict(self)
        data["fingerprints"] = [asdict(item) for item in self.fingerprints]
        return data


def fingerprint_public_page(
    company_id: str,
    url: str,
    *,
    timeout_seconds: float = 8.0,
) -> FingerprintProbeResult:
    """Fetch one public page and return only sanitized ATS references."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            final_url = response.geturl()
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        return _failure(company_id, url, error.geturl(), error.code, f"HTTP {error.code}")
    except (TimeoutError, urllib.error.URLError) as error:
        return _failure(company_id, url, None, None, _safe_error(error))
    if len(body) > MAX_RESPONSE_BYTES:
        return _failure(
            company_id,
            url,
            final_url,
            status_code,
            f"response exceeded {MAX_RESPONSE_BYTES} bytes",
        )
    text = body.decode("utf-8", errors="replace")
    fingerprints = fingerprint_html(text)
    return FingerprintProbeResult(
        company_id=company_id,
        requested_url=url,
        final_url=final_url,
        outcome="matched" if fingerprints else "no_match",
        status_code=status_code,
        detail=f"detected {len(fingerprints)} hosted ATS configuration(s)",
        fingerprints=fingerprints,
    )


def fingerprint_html(markup: str) -> tuple[AtsFingerprint, ...]:
    """Extract unique supported ATS configurations from synthetic or live HTML."""
    normalized = html.unescape(markup).replace("\\/", "/")
    normalized = normalized.replace("\\u002F", "/").replace("\\u002f", "/")
    urls = _candidate_urls(normalized)
    found: dict[tuple[str, tuple[tuple[str, str], ...]], AtsFingerprint] = {}
    for url in urls:
        fingerprint = _fingerprint_url(url)
        if fingerprint is None:
            continue
        key = (
            fingerprint.adapter_type,
            tuple(sorted(fingerprint.adapter_parameters.items())),
        )
        found.setdefault(key, fingerprint)
    return tuple(found.values())


def apply_fingerprint_results(
    proposal_payload: dict[str, object],
    result_payload: Mapping[str, object],
) -> dict[str, object]:
    """Apply only unambiguous fingerprints to already verified search-only sources."""
    proposals = proposal_payload.get("proposals")
    results = result_payload.get("results")
    if not isinstance(proposals, list) or not isinstance(results, list):
        raise ValueError("proposal and fingerprint payloads require arrays")
    proposals_by_id = {item.get("company_id"): item for item in proposals if isinstance(item, dict)}
    for raw_result in results:
        result = _mapping(raw_result, "fingerprint result")
        company_id = _string(result, "company_id", "fingerprint result")
        proposal = proposals_by_id.get(company_id)
        if not isinstance(proposal, dict):
            raise ValueError(f"fingerprint result has unknown company_id: {company_id}")
        fingerprints_raw = result.get("fingerprints")
        if not isinstance(fingerprints_raw, list):
            raise ValueError("fingerprint result.fingerprints must be an array")
        if result.get("outcome") != "matched" or not fingerprints_raw:
            continue
        fingerprints = [_mapping(item, "fingerprint") for item in fingerprints_raw]
        if len(fingerprints) != 1:
            proposal["notes"] = (
                "Multiple hosted ATS configurations detected; H2 inspection required."
            )
            continue
        fingerprint = fingerprints[0]
        adapter_type = _string(fingerprint, "adapter_type", "fingerprint")
        parameters = fingerprint.get("adapter_parameters")
        if not isinstance(parameters, Mapping):
            raise ValueError("fingerprint.adapter_parameters must be an object")
        source_url = _string(fingerprint, "source_url", "fingerprint")
        proposal.update(
            {
                "adapter_type": adapter_type,
                "adapter_parameters": dict(parameters),
                "listing_mode": _string(fingerprint, "listing_mode", "fingerprint"),
                "list_endpoint": _string(fingerprint, "list_endpoint", "fingerprint"),
                "pagination": "Hosted ATS behavior requires adapter verification.",
                "notes": "Hosted ATS detected in verified public careers-page markup.",
            }
        )
        evidence = proposal.setdefault("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("proposal.evidence must be an array")
        item = {
            "url": source_url,
            "evidence_type": "hosted_ats_html_fingerprint",
            "note": f"Detected adapter_type={adapter_type} without retaining page HTML.",
        }
        if item not in evidence:
            evidence.append(item)
    return proposal_payload


def _candidate_urls(markup: str) -> tuple[str, ...]:
    pattern = re.compile(r"https?://[^\s\"'<>]+", flags=re.IGNORECASE)
    trimmed = (match.group(0).rstrip("\\),;]") for match in pattern.finditer(markup))
    return tuple(dict.fromkeys(trimmed))


def _fingerprint_url(url: str) -> AtsFingerprint | None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    segments = [unquote(item) for item in parsed.path.split("/") if item]
    if host == "boards.greenhouse.io" and segments[:3] == ["embed", "job_board", "js"]:
        board_tokens = parse_qs(parsed.query).get("for", [])
        if board_tokens and board_tokens[0]:
            token = board_tokens[0]
            endpoint = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
            return AtsFingerprint(
                "greenhouse",
                {"board_token": token},
                url,
                endpoint,
                "complete_list",
            )
    adapter, parameters, endpoint, mode = infer_adapter(url)
    if adapter != "search_only":
        return AtsFingerprint(adapter, parameters, url, endpoint, mode)
    if host.endswith(".eightfold.ai"):
        tenant = host.split(".")[0]
        return None if tenant == "app" else _simple("eightfold", {"tenant": tenant}, url)
    if host.endswith(".icims.com"):
        customer = host.split(".")[0]
        return _simple("icims", {"customer": customer}, url)
    if host.endswith(".oraclecloud.com"):
        site = _site_after(segments, "sites")
        if site:
            return _simple("oracle_cloud", {"site_number": site}, url)
    if "successfactors" in host:
        company_match = re.search(r"[?&]company=([^&#]+)", url, flags=re.IGNORECASE)
        if company_match:
            return _simple(
                "successfactors",
                {"company_id": unquote(company_match.group(1))},
                url,
            )
    if host.endswith(".taleo.net"):
        organization = host.split(".")[0]
        return _simple("taleo", {"organization": organization}, url)
    if host == "jobs.jobvite.com" and segments:
        return (
            None
            if segments[0].startswith("__")
            else _simple("jobvite", {"company": segments[0]}, url)
        )
    if "darwinbox" in host:
        tenant = host.split(".")[0]
        return _simple("darwinbox", {"tenant": tenant}, url)
    return None


def _simple(adapter: str, parameters: Mapping[str, str], url: str) -> AtsFingerprint:
    return AtsFingerprint(adapter, parameters, url, url, "search_only")


def _site_after(segments: list[str], marker: str) -> str | None:
    lowered = [item.lower() for item in segments]
    if marker not in lowered:
        return None
    index = lowered.index(marker) + 1
    return segments[index] if index < len(segments) else None


def _failure(
    company_id: str,
    requested_url: str,
    final_url: str | None,
    status_code: int | None,
    detail: str,
) -> FingerprintProbeResult:
    return FingerprintProbeResult(
        company_id=company_id,
        requested_url=requested_url,
        final_url=final_url,
        outcome="failed",
        status_code=status_code,
        detail=detail,
        fingerprints=(),
    )


def _safe_error(error: object) -> str:
    return str(error).replace("\r", " ").replace("\n", " ")[:200]


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _string(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string")
    return value.strip()
