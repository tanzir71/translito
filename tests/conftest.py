"""All desktop defaults in tests use an isolated ledger and no real sockets."""
import socket
import pytest
from engines.usage import UsageLedger


@pytest.fixture(scope="session", autouse=True)
def isolated_tcl_runtime(tmp_path_factory):
    """Avoid intermittent shared Python Tcl-file locks on Windows runners."""
    import os
    from pathlib import Path
    import shutil
    import sys
    source = Path(sys.base_prefix) / "tcl"
    if os.name != "nt" or not source.is_dir():
        yield
        return
    folder = tmp_path_factory.mktemp("tcl-runtime")
    for name in ("tcl8.6", "tk8.6", "tcl8"):
        if (source / name).is_dir():
            shutil.copytree(source / name, folder / name)
    saved = {key: os.environ.get(key) for key in ("TCL_LIBRARY", "TK_LIBRARY")}
    os.environ["TCL_LIBRARY"] = str(folder / "tcl8.6")
    os.environ["TK_LIBRARY"] = str(folder / "tk8.6")
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="session")
def tk_parent(isolated_tcl_runtime):
    """Keep one Tk interpreter alive while desktop instances come and go."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture(autouse=True)
def isolated_usage_and_network(tmp_path, monkeypatch):
    from engines.secrets import CredentialStore
    initialize_credentials = CredentialStore.__init__
    def fake_credentials_only(self, backend=None):
        if backend is None:
            raise AssertionError("Tests must inject a credential backend; the real vault is forbidden")
        initialize_credentials(self, backend=backend)
    monkeypatch.setattr(CredentialStore, "__init__", fake_credentials_only)
    original = UsageLedger.__init__
    def initialize(self, path=None, **kwargs):
        original(self, path if path is not None else tmp_path / "default-usage.json", **kwargs)
    monkeypatch.setattr(UsageLedger, "__init__", initialize)
    # Windows asyncio implements its internal socket pair over loopback.
    for operation in ("connect", "connect_ex"):
        original_connect = getattr(socket.socket, operation)
        def guarded(self, address, _connect=original_connect):
            if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}:
                return _connect(self, address)
            raise AssertionError("External network connections are forbidden in automated tests")
        monkeypatch.setattr(socket.socket, operation, guarded)
