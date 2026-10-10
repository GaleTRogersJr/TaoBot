"""Windows-user-scoped DPAPI credentials; never persist plaintext or print keys."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys


class CredentialError(Exception):
    """A safe user-facing credential-storage failure (never contains a key)."""


def validate_key(value):
    key = value.strip() if isinstance(value, str) else ""
    if not key or len(key) > 4096 or any(ord(ch) < 32 or ord(ch) > 126 for ch in key):
        raise CredentialError("Enter a nonempty printable API key (maximum 4096 characters).")
    return key


class WindowsDPAPI:
    entropy = b"GRSoftware.SubnetWatch.Taostats.v1"

    def _transform(self, data, decrypt):
        if sys.platform != "win32":
            raise CredentialError("Saving credentials securely requires Windows DPAPI. No plaintext fallback is available.")

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        crypto = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        source_buffer = ctypes.create_string_buffer(data)
        entropy_buffer = ctypes.create_string_buffer(self.entropy)
        source = Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        entropy = Blob(len(self.entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = Blob()
        kernel.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel.LocalFree.restype = wintypes.HLOCAL
        protect = crypto.CryptProtectData
        protect.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), wintypes.LPVOID,
                            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(Blob)]
        protect.restype = wintypes.BOOL
        unprotect = crypto.CryptUnprotectData
        unprotect.argtypes = [ctypes.POINTER(Blob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(Blob),
                              wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(Blob)]
        unprotect.restype = wintypes.BOOL
        description = wintypes.LPWSTR()
        try:
            # CRYPTPROTECT_UI_FORBIDDEN=1. Do NOT set LOCAL_MACHINE=4:
            # only the current Windows user can decrypt this credential.
            success = (unprotect(ctypes.byref(source), ctypes.byref(description), ctypes.byref(entropy), None,
                                 None, 1, ctypes.byref(output)) if decrypt else
                       protect(ctypes.byref(source), "GR Software Taostats", ctypes.byref(entropy), None,
                               None, 1, ctypes.byref(output)))
            if not success:
                raise CredentialError("Windows could not unlock this saved credential. It may belong to another user or be damaged." if decrypt else
                                      "Windows could not protect the API key. Nothing was saved.")
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                # Erase decrypted output before releasing the Windows buffer.
                if decrypt:
                    ctypes.memset(output.pbData, 0, output.cbData)
                kernel.LocalFree(ctypes.cast(output.pbData, wintypes.HLOCAL))
            if description:
                kernel.LocalFree(ctypes.cast(description, wintypes.HLOCAL))
            ctypes.memset(source_buffer, 0, len(source_buffer))

    def protect(self, data):
        return self._transform(data, False)

    def unprotect(self, data):
        return self._transform(data, True)


class CredentialStore:
    magic = b"GRDPAPI1\x00"

    def __init__(self, path, protector=None):
        self.path = Path(path)
        self.protector = protector or WindowsDPAPI()

    @classmethod
    def for_database(cls, database_path, protector=None):
        return cls(Path(database_path).with_suffix(".taostats.dpapi"), protector)

    @property
    def exists(self):
        return self.path.is_file()

    def save(self, key):
        key = validate_key(key)
        try:
            encrypted = self.protector.protect(key.encode("utf-8"))
            if not isinstance(encrypted, bytes) or not encrypted:
                raise CredentialError("Secure credential storage returned an invalid encrypted value.")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".new")
            try:
                with temporary.open("wb") as stream:
                    stream.write(self.magic + encrypted)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("Could not save the protected credential. Check the data-folder permissions.") from None

    def load(self):
        if not self.exists:
            return None
        try:
            protected = self.path.read_bytes()
            if len(protected) > 20000 or not protected.startswith(self.magic):
                raise CredentialError("Saved credential is damaged. Replace or forget it in Settings.")
            decrypted = self.protector.unprotect(protected[len(self.magic):])
            return validate_key(decrypted.decode("utf-8"))
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("Could not unlock the saved credential for this Windows user. Replace or forget it in Settings.") from None

    def delete(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            raise CredentialError("Could not forget the saved credential. Check the data-folder permissions.") from None


def provision_taostats(key, database_path):
    """Provision from trusted hidden input. Returns no key; never logs it.

    Use the application's data/watch.sqlite3 path, then start the program.
    Saving is Windows-user-scoped and does not validate provider access.
    """
    from .storage import Store
    from .polling import DEFAULT_INTERVAL
    CredentialStore.for_database(database_path).save(key)
    store = Store(database_path)
    try:
        store.set_setting("mode", "taostats")
        store.set_setting("interval", DEFAULT_INTERVAL)
        store.set_setting("polling", None)
    finally:
        store.close()
