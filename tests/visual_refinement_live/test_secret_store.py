"""Credential boundary tests use only fake providers and fake Win32 calls."""
import ctypes
from types import SimpleNamespace

import pytest

from src.visual_refinement_live import secret_store as secrets
from src.visual_refinement_live import jev_client


class FakeProvider:
    def __init__(self, value=None):
        self.value = value
        self.calls = 0

    def get_secret(self):
        self.calls += 1
        if self.value is None:
            raise secrets.SecretUnavailable()
        return self.value


def test_real_evaluator_uses_only_injected_provider(monkeypatch):
    provider = FakeProvider("synthetic-test-value")
    received = []
    class FakeSDKTransport:
        def __init__(self, value):
            received.append(value)
    monkeypatch.setattr(jev_client, "SDKTransport", FakeSDKTransport)
    evaluator = jev_client.JevEvaluator(None, None, origin="REAL_JEV",
                                         secret_provider=provider)
    try:
        assert provider.calls == 1
        assert received == ["synthetic-test-value"]
    finally:
        evaluator.close()


def test_absent_secret_stops_before_evaluator_or_transport(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(jev_client, "SDKTransport", lambda _: pytest.fail("transport created"))
    with pytest.raises(secrets.SecretUnavailable, match="^SECRET_UNAVAILABLE$"):
        jev_client.JevEvaluator(None, None, origin="REAL_JEV", secret_provider=provider)
    assert provider.calls == 1


def test_fixture_and_injected_transport_never_read_provider():
    provider = FakeProvider()
    transport = object()
    for origin in ("FIXTURE", "REAL_JEV"):
        evaluator = jev_client.JevEvaluator(None, None, origin=origin,
                                             secret_provider=provider,
                                             transport=transport)
        assert evaluator.transport is transport
        evaluator.close()
    assert provider.calls == 0


def test_registration_requires_interactive_console_without_reading_store(monkeypatch, capsys):
    monkeypatch.setattr(secrets.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(secrets, "_api", lambda: pytest.fail("store accessed"))
    assert secrets.main(["register"]) == 2
    assert "SECRET_UNAVAILABLE" in capsys.readouterr().err


def test_fake_win32_read_and_free(monkeypatch):
    native = (ctypes.c_ubyte * 12)(*b"fixture-only")
    cred = secrets._CREDENTIALW()
    cred.Type = 1
    cred.TargetName = secrets.TARGET_NAME
    cred.CredentialBlobSize = 12
    cred.CredentialBlob = ctypes.cast(native, ctypes.POINTER(ctypes.c_ubyte))
    freed = []
    class FakeApi:
        def CredReadW(self, target, kind, flags, out):
            assert (target, kind, flags) == (secrets.TARGET_NAME, 1, 0)
            ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(secrets._CREDENTIALW)))[0] = ctypes.pointer(cred)
            return True
        def CredFree(self, ptr):
            freed.append(bool(ptr))
    monkeypatch.setattr(secrets, "_api", FakeApi)
    assert secrets.WindowsCredentialManager().get_secret() == "fixture-only"
    assert freed == [True]


def test_fake_win32_registration_is_no_echo_and_never_overwrites(monkeypatch, capsys):
    seen = []
    class FakeApi:
        def __init__(self):
            self.existing = False
        def CredReadW(self, target, kind, flags, out):
            assert target == secrets.TARGET_NAME
            ctypes.set_last_error(1168)
            return False
        def CredWriteW(self, pointer, flags):
            cred = ctypes.cast(pointer, ctypes.POINTER(secrets._CREDENTIALW)).contents
            seen.append((cred.TargetName, cred.Type, cred.Persist,
                         ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)))
            return True
    monkeypatch.setattr(secrets, "_api", FakeApi)
    monkeypatch.setattr(secrets.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(secrets.sys, "stderr", SimpleNamespace(isatty=lambda: True, write=lambda _: None))
    monkeypatch.setattr(secrets.getpass, "getpass", lambda _: "synthetic-test-value")
    assert secrets.main(["register"]) == 0
    assert seen == [(secrets.TARGET_NAME, 1, 2, b"synthetic-test-value")]
    assert "synthetic-test-value" not in capsys.readouterr().out


def test_registration_refuses_existing_credential(monkeypatch):
    existing = secrets._CREDENTIALW()
    released = []
    class FakeApi:
        def CredReadW(self, target, kind, flags, out):
            ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(secrets._CREDENTIALW)))[0] = ctypes.pointer(existing)
            return True
        def CredFree(self, pointer):
            released.append(bool(pointer))
        def CredWriteW(self, *args):
            pytest.fail("existing credential overwritten")
    monkeypatch.setattr(secrets, "_api", FakeApi)
    with pytest.raises(secrets.SecretUnavailable, match="^SECRET_UNAVAILABLE$"):
        secrets.WindowsCredentialManager().register_secret("synthetic-test-value")
    assert released == [True]


def test_evaluator_never_opens_env_or_secret_files(monkeypatch):
    provider = FakeProvider("synthetic-test-value")
    monkeypatch.setattr(jev_client, "SDKTransport", lambda value: object())
    def no_files(*args, **kwargs):
        pytest.fail("evaluator attempted a file open")
    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", no_files)
        patch.setattr("pathlib.Path.open", no_files)
        for origin, kwargs in (("FIXTURE", {"transport": object()}),
                               ("REAL_JEV", {"secret_provider": provider})):
            evaluator = jev_client.JevEvaluator(None, None, origin=origin, **kwargs)
            evaluator.close()
        with pytest.raises(secrets.SecretUnavailable, match="^SECRET_UNAVAILABLE$"):
            jev_client.JevEvaluator(None, None, origin="REAL_JEV",
                                     secret_provider=FakeProvider())
    assert provider.calls == 1
