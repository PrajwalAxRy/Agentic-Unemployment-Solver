"""Tests for company registry loading, validation, and full-seed accounting."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from job_finder.core.company_registry import load_company_registry


def load_raw_registry() -> dict[str, object]:
    return {
        "schema_version": 1,
        "registry_version": "test",
        "generated_at": "2026-09-20T00:00:00+05:30",
        "discovery_batch_id": "test-batch",
        "sources": [
            {
                "schema_version": 1,
                "company_id": "example",
                "company_name": "Example",
                "source_rank": 1,
                "priority": "P1",
                "last_verified_at": None,
                "status": "unresolved",
                "careers_url": None,
                "adapter_type": "unresolved",
                "adapter_parameters": {},
                "identity_strategy": "unresolved",
                "date_strategy": {
                    "field_name": None,
                    "basis": "unknown",
                    "verified_as_publication": False,
                    "notes": "Test source.",
                },
                "detail_strategy": "unresolved",
                "enabled": False,
                "confidence": "unknown",
                "evidence": [],
                "low_confidence_approved": False,
                "exception_reason": None,
                "notes": "Test source.",
            }
        ],
    }


def write_registry(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_registry_loads_source_metadata(tmp_path: Path) -> None:
    registry = load_company_registry(write_registry(tmp_path, load_raw_registry()))

    assert registry.registry_version == "test"
    assert registry.entries[0].source.company_id == "example"
    assert registry.entries[0].priority == "P1"


def test_duplicate_company_ids_fail(tmp_path: Path) -> None:
    payload = load_raw_registry()
    sources = payload["sources"]
    assert isinstance(sources, list)
    sources.append(deepcopy(sources[0]))

    with pytest.raises(ValueError, match="duplicate company IDs"):
        load_company_registry(write_registry(tmp_path, payload))


def test_source_verification_cannot_postdate_registry_generation(tmp_path: Path) -> None:
    payload = load_raw_registry()
    sources = payload["sources"]
    assert isinstance(sources, list)
    assert isinstance(sources[0], dict)
    sources[0]["last_verified_at"] = "2026-09-20T00:00:01+05:30"

    with pytest.raises(ValueError, match="later than registry.generated_at: example"):
        load_company_registry(write_registry(tmp_path, payload))


def test_unknown_adapter_name_fails(tmp_path: Path) -> None:
    payload = load_raw_registry()
    sources = payload["sources"]
    assert isinstance(sources, list)
    assert isinstance(sources[0], dict)
    sources[0]["adapter_type"] = "mystery_ats"

    with pytest.raises(ValueError, match="adapter_type must be one of"):
        load_company_registry(write_registry(tmp_path, payload))


def test_adapter_specific_missing_parameters_fail(tmp_path: Path) -> None:
    payload = load_raw_registry()
    sources = payload["sources"]
    assert isinstance(sources, list)
    assert isinstance(sources[0], dict)
    sources[0]["adapter_type"] = "greenhouse"
    sources[0]["adapter_parameters"] = {}

    with pytest.raises(ValueError, match="requires parameters: board_token"):
        load_company_registry(write_registry(tmp_path, payload))


def test_enabled_low_confidence_source_requires_approval(tmp_path: Path) -> None:
    payload = load_raw_registry()
    sources = payload["sources"]
    assert isinstance(sources, list)
    candidate = sources[0]
    assert isinstance(candidate, dict)
    candidate["careers_url"] = "https://jobs.example.com"
    candidate["adapter_type"] = "search_only"
    candidate["adapter_parameters"] = {"search_url": "https://jobs.example.com"}
    candidate["confidence"] = "low"
    candidate["evidence"] = ["https://jobs.example.com"]
    candidate["enabled"] = True
    candidate["status"] = "enabled"
    candidate["low_confidence_approved"] = False

    with pytest.raises(ValueError, match="requires explicit approval"):
        load_company_registry(write_registry(tmp_path, payload))


@pytest.mark.parametrize("status", ["blocked", "unsupported"])
def test_blocked_and_unsupported_sources_require_reason(
    tmp_path: Path,
    status: str,
) -> None:
    payload = load_raw_registry()
    sources = payload["sources"]
    assert isinstance(sources, list)
    assert isinstance(sources[0], dict)
    sources[0]["status"] = status
    sources[0]["exception_reason"] = None

    with pytest.raises(ValueError, match="requires exception_reason"):
        load_company_registry(write_registry(tmp_path, payload))
