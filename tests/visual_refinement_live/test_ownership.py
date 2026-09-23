"""Only one live writer may own the same new-run root."""
import pytest

from src.visual_refinement_live import ownership


def test_writer_lease_rejects_second_process_style_handle(tmp_path, monkeypatch):
    monkeypatch.setattr(ownership, "RUNS_ROOT", tmp_path / "owned")
    first = ownership.WriterLease()
    second = ownership.WriterLease()
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="owned_live_writer_already_active"):
            second.acquire()
    finally:
        second.close()
        first.close()
    second.acquire()
    second.close()
