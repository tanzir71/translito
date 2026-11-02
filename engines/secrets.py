"""Windows Credential Manager only; never a file/environment fallback."""
import re
import sys


class CredentialError(RuntimeError):
    pass


class CredentialStore:
    service = "Translito"

    def __init__(self, backend=None):
        if backend is None:
            if sys.platform != "win32":
                raise CredentialError("Cloud keys require Windows Credential Manager in this Windows app.")
            try:
                from keyring.backends.Windows import WinVaultKeyring
                backend = WinVaultKeyring()
            except Exception:
                raise CredentialError("Could not open Windows Credential Manager.") from None
        self.backend = backend

    @staticmethod
    def _provider(provider):
        if not re.fullmatch(r"[a-z0-9_-]+", provider):
            raise CredentialError("Invalid provider identifier.")
        return provider

    def get(self, provider):
        provider = self._provider(provider)
        try:
            return self.backend.get_password(self.service, provider)
        except Exception:
            raise CredentialError("Could not read the key from Windows Credential Manager.") from None

    def save(self, provider, key):
        provider = self._provider(provider)
        key = key.strip()
        if not key or len(key) > 4000 or "\n" in key or "\r" in key:
            raise CredentialError("Enter a valid single-line key.")
        try:
            self.backend.set_password(self.service, provider, key)
        except Exception:
            raise CredentialError("Could not save the key in Windows Credential Manager.") from None
