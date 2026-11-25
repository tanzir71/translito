import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import gui


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("v2-ui")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("TRANSLITO_UI_PREVIEW", "1")
    monkeypatch.setattr(gui, "CONFIG_FILE", tmp_path / "config.ini")
    monkeypatch.setattr(gui, "is_open_at_login_enabled", lambda: False)
    monkeypatch.setattr(gui, "query_input_devices", lambda **kw: [])
    monkeypatch.setattr(gui, "query_output_devices", lambda: [])
    monkeypatch.setattr(gui.TranslatorGUI, "refresh_voices", lambda self: None)
    root = tk.Tk()
    value = gui.TranslatorGUI(root)
    root.update()
    yield value
    value.preferences.close()
    root.destroy()
    monkeypatch.undo()


def test_settings_sidebar_dimensions_and_section_layout(app):
    app.open_settings()
    app.settings_window.transient("")
    app.settings_window.deiconify()
    app.settings_window.update()
    assert app.settings_window.wm_geometry().split("+")[0] == "820x680"
    assert tuple(app.settings_shell.pages) == ("Languages", "Engine", "Cost & usage", "Subtitles", "Schedule", "Audio", "Models", "General")
    for page in app.settings_shell.pages:
        app.settings_shell.show(page)
        assert app.settings_shell.pages[page].winfo_manager() == "pack"
        assert all(not widget.winfo_manager() for name, widget in app.settings_shell.pages.items() if name != page)


def test_all_entry_states_are_dark(app):
    for name in ("TEntry", "TCombobox", "TSpinbox", "Dark.TEntry", "Dark.TCombobox"):
        for state in ((), ("readonly",), ("focus",), ("disabled",), ("disabled", "readonly")):
            assert app.style.lookup(name, "fieldbackground", state) in {gui.COLORS["field"], gui.COLORS["surface"]}
    entry = tk.Entry(app.root)
    assert entry.cget("background") == gui.COLORS["field"]
    assert entry.cget("foreground") == gui.COLORS["text"]


def test_windows_titlebar_requests_dark_caption():
    from ui_theme import dark_titlebar
    dwm = Mock()
    dark_titlebar(SimpleNamespace(winfo_id=lambda: 123), dwm=dwm, user32=SimpleNamespace(GetParent=lambda h: h))
    assert [call.args[1] for call in dwm.DwmSetWindowAttribute.call_args_list] == [20, 35, 36]
