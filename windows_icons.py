"""Exact-size Windows icon handles; other platforms retain the PIL backend."""
import ctypes
from pathlib import Path
import sys


def resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def icon_path():
    root = resources()
    return root / "Translito.ico" if (root / "Translito.ico").is_file() else root / "installer" / "Translito.ico"


def icon_metrics(user32, *, small=False, dpi=None):
    dpi = dpi or (user32.GetDpiForSystem() if hasattr(user32, "GetDpiForSystem") else 96) or 96
    metric = 49 if small else 11
    if hasattr(user32, "GetSystemMetricsForDpi"):
        return user32.GetSystemMetricsForDpi(metric, dpi), user32.GetSystemMetricsForDpi(metric+1, dpi)
    return user32.GetSystemMetrics(metric), user32.GetSystemMetrics(metric+1)


def load_icon(path, user32, *, small=False, dpi=None):
    width, height = icon_metrics(user32, small=small, dpi=dpi)
    if isinstance(user32, ctypes.CDLL):
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    handle = user32.LoadImageW(None, str(path), 1, width, height, 0x10)
    if not handle:
        raise OSError("The icon could not be loaded")
    return handle


def apply_window_icon(window, *, user32=None, path=None, dpi=None):
    path = Path(path) if path else icon_path()
    try:
        window.iconbitmap(default=str(path))
    except Exception:
        pass
    if sys.platform != "win32" and user32 is None:
        return
    user32 = user32 or ctypes.windll.user32
    try:
        if isinstance(user32, ctypes.CDLL):
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.DestroyIcon.argtypes = [ctypes.c_void_p]
            user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        handles = []
        for small, kind in ((False, 1), (True, 0)):
            handle = load_icon(path, user32, small=small, dpi=dpi)
            user32.SendMessageW(hwnd, 0x80, kind, handle)
            handles.append(handle)
        for handle in getattr(window, "_native_icon_handles", ()):
            user32.DestroyIcon(handle)
        window._native_icon_handles = handles
        if not getattr(window, "_native_icon_cleanup", False):
            def cleanup(event):
                if event.widget is window:
                    for handle in getattr(window, "_native_icon_handles", ()):
                        user32.DestroyIcon(handle)
                    window._native_icon_handles = []
            window.bind("<Destroy>", cleanup, add="+")
            window._native_icon_cleanup = True
    except (OSError, AttributeError, TypeError):
        pass


def tray_icon_class(base=None, *, user32=None, directory=None):
    if base is None:
        import pystray
        base = pystray.Icon
    if sys.platform != "win32" and user32 is None:
        return base
    if not hasattr(base, "_assert_icon_handle"):
        return base
    api = user32 or ctypes.windll.user32
    folder = Path(directory) if directory else resources() / "engines" / "data" / "tray"
    class ExactSizeIcon(base):
        state = "idle"
        def _assert_icon_handle(self):
            if self._icon_handle:
                return
            try:
                self._icon_handle = load_icon(folder / f"{self.state}.ico", api, small=True)
            except (OSError, AttributeError):
                super()._assert_icon_handle()
        def set_state(self, state):
            if state != self.state:
                self.state = state
                self._update_icon()
    return ExactSizeIcon
