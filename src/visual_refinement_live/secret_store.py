"""TypeSafe credential access through the current Windows user's credential vault.

The module has no credential-store side effects on import. Registration is an
explicit, local, interactive action; only real Jev evaluation reads the value.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import getpass
import sys
from typing import Protocol
import warnings


TARGET_NAME = "JevVisualRefinement/TypeSafe"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_MAX_BLOB_BYTES = 5 * 512


class SecretUnavailable(ValueError):
    def __init__(self):
        super().__init__("SECRET_UNAVAILABLE")


class SecretProvider(Protocol):
    def get_secret(self) -> str: ...


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _api():
    if sys.platform != "win32":
        raise SecretUnavailable()
    try:
        dll = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                  wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
        dll.CredReadW.restype = wintypes.BOOL
        dll.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        dll.CredWriteW.restype = wintypes.BOOL
        dll.CredFree.argtypes = [ctypes.c_void_p]
        dll.CredFree.restype = None
        return dll
    except (AttributeError, OSError):
        raise SecretUnavailable() from None


def _validate(value: str) -> str:
    if not value or len(value) > _MAX_BLOB_BYTES or any(
            ord(ch) < 33 or ord(ch) > 126 for ch in value):
        raise SecretUnavailable()
    return value


class WindowsCredentialManager:
    """Current-user generic credential, fixed target, local-machine persistence."""

    def get_secret(self) -> str:
        api = _api()
        found = ctypes.POINTER(_CREDENTIALW)()
        if not api.CredReadW(TARGET_NAME, _CRED_TYPE_GENERIC, 0,
                             ctypes.byref(found)):
            raise SecretUnavailable()
        try:
            cred = found.contents
            if (cred.Type != _CRED_TYPE_GENERIC or
                    not cred.TargetName or
                    cred.TargetName.casefold() != TARGET_NAME.casefold() or
                    not 0 < cred.CredentialBlobSize <= _MAX_BLOB_BYTES or
                    not cred.CredentialBlob):
                raise SecretUnavailable()
            data = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            try:
                return _validate(data.decode("ascii"))
            except UnicodeError:
                raise SecretUnavailable() from None
        finally:
            api.CredFree(found)

    def register_secret(self, value: str) -> None:
        _validate(value)
        api = _api()
        existing = ctypes.POINTER(_CREDENTIALW)()
        if api.CredReadW(TARGET_NAME, _CRED_TYPE_GENERIC, 0,
                             ctypes.byref(existing)):
            api.CredFree(existing)
            raise SecretUnavailable()
        if ctypes.get_last_error() != 1168:  # ERROR_NOT_FOUND
            raise SecretUnavailable()
        blob = bytearray(value, "ascii")
        native = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _CREDENTIALW()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = TARGET_NAME
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(native, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "TypeSafe"
        try:
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise SecretUnavailable()
        finally:
            for index in range(len(blob)):
                blob[index] = 0
                native[index] = 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["register"]:
        print("usage: python -m src.visual_refinement_live.secret_store register",
              file=sys.stderr)
        return 2
    if sys.platform != "win32" or not sys.stdin.isatty() or not sys.stderr.isatty():
        print("SECRET_UNAVAILABLE: interactive Windows console required", file=sys.stderr)
        return 2
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("TypeSafe API key: ")
        WindowsCredentialManager().register_secret(value)
    except (SecretUnavailable, getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("SECRET_UNAVAILABLE", file=sys.stderr)
        return 2
    finally:
        value = None
    print(f"Credential registered: {TARGET_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
