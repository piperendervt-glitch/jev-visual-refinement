"""Single-writer process lease for approved live runs in this checkout."""
from __future__ import annotations

import msvcrt
import os

from .store import RUNS_ROOT


class WriterLease:
    def __init__(self):
        RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = RUNS_ROOT / "writer.lock"
        self.stream = None
        self.acquired = False

    def acquire(self) -> None:
        if self.stream is not None:
            raise ValueError("writer_lease_reused")
        self.stream = self.path.open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
            os.fsync(self.stream.fileno())
        self.stream.seek(0)
        try:
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise RuntimeError("owned_live_writer_already_active") from exc
        self.acquired = True

    def close(self) -> None:
        if self.stream is None:
            return
        if self.acquired:
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()
        self.stream = None
        self.acquired = False
