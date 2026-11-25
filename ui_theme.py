"""Shared dark input and Windows chrome styling, including readonly states."""
import sys


def input_styles(root, style, colors):
    for widget in ("Entry", "Spinbox", "Text", "Listbox"):
        for option, value in (("background", colors["field"]), ("foreground", colors["text"]),
                              ("selectBackground", colors["blue"]), ("selectForeground", colors["on_accent"]),
                              ("insertBackground", colors["text"]), ("highlightBackground", colors["border"]),
                              ("highlightColor", colors["blue"]), ("disabledBackground", colors["surface"]),
                              ("disabledForeground", colors["tertiary"]), ("readonlyBackground", colors["field"])):
            root.option_add(f"*{widget}.{option}", value)
    for name in ("TEntry", "TCombobox", "TSpinbox", "Dark.TEntry", "Dark.TCombobox"):
        style.configure(name, fieldbackground=colors["field"], background=colors["field"],
            foreground=colors["text"], insertcolor=colors["text"], arrowcolor=colors["secondary"],
            bordercolor=colors["border"], lightcolor=colors["border"], darkcolor=colors["border"], padding=6)
        style.map(name,
            fieldbackground=[("disabled", colors["surface"]), ("readonly", colors["field"]), ("!disabled", colors["field"])],
            foreground=[("disabled", colors["tertiary"]), ("!disabled", colors["text"])],
            selectbackground=[("!disabled", colors["field"])], selectforeground=[("!disabled", colors["text"])])


def dark_titlebar(window, *, dwm=None, user32=None):
    if sys.platform != "win32" and dwm is None:
        return
    import ctypes
    try:
        dwm = dwm or ctypes.windll.dwmapi
        user32 = user32 or ctypes.windll.user32
        handle = user32.GetParent(window.winfo_id()) or window.winfo_id()
        for attribute, value in ((20, 1), (35, 0x1f1f1f), (36, 0xf5f3f3)):
            number = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(handle, attribute, ctypes.byref(number), ctypes.sizeof(number))
    except (AttributeError, OSError):
        pass  # Older Windows versions retain their system chrome.
