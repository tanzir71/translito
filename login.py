import os
from pathlib import Path
import sys


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Translito"


def default_startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    gui_path = Path(__file__).with_name("gui.py")
    return f'"{sys.executable}" "{gui_path}"'


def is_open_at_login_enabled(command=None):
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE_NAME)
        if command is None:
            return bool(value)
        return value == command
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_open_at_login(enabled, command=None):
    if os.name != "nt":
        return False, "Open at login is only available on Windows."
    command = command or default_startup_command()
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except Exception as exc:
        return False, str(exc)
