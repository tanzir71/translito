import tkinter as tk
import pytest

from settings_state import CONTROL_VARIABLES, SettingsState


@pytest.fixture(scope="module")
def tcl():
    return tk.Tcl()


@pytest.mark.parametrize("control", CONTROL_VARIABLES)
def test_every_existing_control_saves_without_a_save_button_and_restores(tmp_path, control, tcl):
    path = tmp_path / "config.ini"
    path.write_text("; preserve me\n[UNKNOWN]\nvalue = retained\n")
    first = SettingsState(path)
    var = first.bind(tk.StringVar(tcl), "UI", control, "old")
    var.set("changed " + control)
    first.close()
    restarted = SettingsState(path)
    restored = restarted.bind(tk.StringVar(tcl), "UI", control, "default")
    assert restored.get() == "changed " + control
    assert path.read_text().startswith("; preserve me\n[UNKNOWN]\nvalue = retained\n")


def test_typed_bindings_and_preview_are_safe(tmp_path, tcl):
    path = tmp_path / "config.ini"
    state = SettingsState(path)
    boolean = state.bind(tk.BooleanVar(tcl), "UI", "toggle", False)
    boolean.set(True)
    assert SettingsState(path).get("UI", "toggle", False) is True
    geometry = state.bind(tk.StringVar(tcl), "UI", "window_geometry", "760x560")
    geometry.set("820x680+100+200")
    assert SettingsState(path).get("UI", "window_geometry", "") == "820x680+100+200"
    before = path.read_bytes()
    preview = SettingsState(path, writable=lambda: False)
    preview.bind(tk.BooleanVar(tcl), "UI", "toggle", False).set(False)
    assert path.read_bytes() == before
