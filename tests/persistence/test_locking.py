"""Tests for the single-run operating-system lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_finder.persistence.locking import ScanAlreadyRunningError, ScanLock


def test_overlapping_scan_attempt_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "state" / "scan.lock"

    with ScanLock(path) as first:
        assert first.acquired is True
        with (
            pytest.raises(ScanAlreadyRunningError, match="already running"),
            ScanLock(path),
        ):
            pytest.fail("overlapping lock must not be acquired")

    assert first.acquired is False


def test_lock_can_be_reacquired_after_clean_release(tmp_path: Path) -> None:
    path = tmp_path / "scan.lock"

    with ScanLock(path):
        pass
    with ScanLock(path) as second:
        assert second.acquired is True


def test_exception_releases_lock(tmp_path: Path) -> None:
    path = tmp_path / "scan.lock"

    with pytest.raises(RuntimeError, match="test interruption"), ScanLock(path):
        raise RuntimeError("test interruption")

    with ScanLock(path) as recovered:
        assert recovered.acquired is True


def test_same_instance_cannot_be_acquired_twice(tmp_path: Path) -> None:
    lock = ScanLock(tmp_path / "scan.lock")
    try:
        lock.acquire()
        with pytest.raises(RuntimeError, match="already acquired"):
            lock.acquire()
    finally:
        lock.release()
