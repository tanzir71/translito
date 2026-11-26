"""System-DPI layout units. Fonts remain in Tk point units."""
import ctypes
import os
import re


class Pixels(int):
    """Mark an already-scaled value when helpers forward widget dimensions."""


def system_dpi(api=None):
    try:
        api = api or ctypes.windll.user32
        return api.GetDpiForSystem() or 96
    except (AttributeError, OSError):
        return 96


def scale():
    try:
        return min(4., max(.5, float(os.environ.get("TRANSLITO_UI_SCALE", system_dpi()/96))))
    except ValueError:
        return system_dpi()/96


def px(value, *, chars=False):
    if isinstance(value, (tuple, list)):
        return tuple(px(item, chars=chars) for item in value)
    if isinstance(value, Pixels):
        return value
    return Pixels(round(value if chars else value * scale()))


def scaled_geometry(value, *, factor=None):
    match = re.fullmatch(r"(\d+)x(\d+)((?:[+-]\d+){2})?", value)
    if not match:
        return value
    factor = scale() if factor is None else factor
    return f"{round(int(match[1])*factor)}x{round(int(match[2])*factor)}" + (match[3] or "")


def restore_geometry(value, saved_dpi=96):
    return scaled_geometry(value, factor=96*scale()/max(1, float(saved_dpi)))


def configure_scale(root):
    root.tk.call("tk", "scaling", 96*scale()/72)


def enable_system_dpi_awareness(*, shcore=None, user32=None):
    try:
        (shcore or ctypes.windll.shcore).SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            (user32 or ctypes.windll.user32).SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
