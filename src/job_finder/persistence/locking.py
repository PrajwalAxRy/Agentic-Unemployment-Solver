"""Cross-platform advisory lock preventing overlapping scan processes."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Protocol, cast


class ScanAlreadyRunningError(RuntimeError):
    """Another process currently holds the scan lock."""


class ScanLock:
    """Non-blocking operating-system lock held for one scan run."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        """Whether this instance currently owns the operating-system lock."""
        return self._stream is not None

    def acquire(self) -> None:
        """Acquire immediately or raise when another run owns the lock."""
        if self._stream is not None:
            raise RuntimeError("scan lock is already acquired by this instance")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            _ensure_lock_byte(stream)
            _lock_nonblocking(stream)
        except OSError as error:
            stream.close()
            raise ScanAlreadyRunningError(
                f"another job-finder scan is already running (lock: {self.path.resolve()})"
            ) from error
        self._stream = stream

    def release(self) -> None:
        """Release the held lock; the harmless lock file remains for reuse."""
        stream = self._stream
        if stream is None:
            return
        try:
            _unlock(stream)
        finally:
            stream.close()
            self._stream = None

    def __enter__(self) -> ScanLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


def _ensure_lock_byte(stream: BinaryIO) -> None:
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"\0")
        stream.flush()
        os.fsync(stream.fileno())
    stream.seek(0)


if os.name == "nt":
    import msvcrt

    def _lock_nonblocking(stream: BinaryIO) -> None:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(stream: BinaryIO) -> None:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

else:

    class _FcntlModule(Protocol):
        LOCK_EX: int
        LOCK_NB: int
        LOCK_UN: int

        def flock(self, file_descriptor: int, operation: int) -> None: ...

    _fcntl = cast(_FcntlModule, import_module("fcntl"))

    def _lock_nonblocking(stream: BinaryIO) -> None:
        _fcntl.flock(stream.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)

    def _unlock(stream: BinaryIO) -> None:
        _fcntl.flock(stream.fileno(), _fcntl.LOCK_UN)
