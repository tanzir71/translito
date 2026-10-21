"""Use the Windows certificate store for application HTTPS requests."""

import sys


_configured = False


def configure_native_tls():
    """Keep TLS verification on while recognizing Windows-trusted roots."""
    global _configured
    if _configured or sys.platform != "win32":
        return

    import truststore

    truststore.inject_into_ssl()
    _configured = True
