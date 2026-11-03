"""Initialize COM on the thread that enumerates or records Windows audio."""
from contextlib import contextmanager
import ctypes
import sys


def _load_com_api():
    if sys.platform != "win32":
        return None
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    return ole32


@contextmanager
def audio_com_context():
    """Balance this thread's COM reference; respect an existing STA apartment."""
    ole32 = _load_com_api()
    if ole32 is None:
        yield
        return
    result = ole32.CoInitializeEx(None, 0) & 0xFFFFFFFF  # COINIT_MULTITHREADED
    owned = result in (0, 1)  # S_OK and S_FALSE both add a reference.
    if not owned and result != 0x80010106:  # RPC_E_CHANGED_MODE: already STA.
        raise OSError(f"Windows audio initialization failed (HRESULT 0x{result:08X}).")
    try:
        yield
    finally:
        if owned:
            ole32.CoUninitialize()
