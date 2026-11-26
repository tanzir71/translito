from types import SimpleNamespace
from unittest.mock import Mock
import sys

from hotkeys import GlobalHotkeyManager


def test_failed_shortcut_edit_restores_previous_working_registrations(monkeypatch):
    current, errors = {}, []
    def add(combo, callback):
        if combo == "invalid":
            raise ValueError("Unsupported shortcut")
        handle = object()
        current[handle] = (combo, callback)
        return handle
    keyboard = SimpleNamespace(add_hotkey=add, remove_hotkey=lambda handle: current.pop(handle))
    monkeypatch.setitem(sys.modules, "keyboard", keyboard)
    callback = Mock()
    manager = GlobalHotkeyManager({"listen": callback, "speak": Mock()}, on_error=errors.append)
    assert manager.register({"listen": "ctrl+l"})
    assert not manager.register({"listen": "ctrl+x", "speak": "invalid"})
    assert [combo for combo, _ in current.values()] == ["ctrl+l"]
    assert manager.last_registered == {"listen": "ctrl+l"} and errors == ["Unsupported shortcut"]
    manager.unregister()
    assert not current
