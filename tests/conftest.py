"""All desktop defaults in tests use an isolated ledger and no real sockets."""
import socket
import pytest
from engines.usage import UsageLedger


@pytest.fixture(autouse=True)
def isolated_usage_and_network(tmp_path, monkeypatch):
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
