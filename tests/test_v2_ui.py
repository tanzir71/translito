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
    # Some Windows runners briefly deny reads of Python's shared Tcl scripts.
    # Retry that environment failure; widget/configuration failures still fail.
    import time
    for attempt in range(4):
        try:
            root = tk.Tk()
            break
        except tk.TclError as error:
            if "Can't find a usable" not in str(error) or attempt == 3:
                monkeypatch.undo()
                raise
            time.sleep(.1)
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


def test_main_dimensions_app_bar_and_translation_order(app):
    assert app.root.wm_geometry().split("+")[0] == "800x640"
    assert app.listen_mode_button.cget("text") == "Listen"
    assert app.speak_mode_button.cget("text") == "Speak"
    assert app.settings_image.width() == app.settings_image.height() == 15
    app.subtitle_switch.toggle()
    assert app.subtitles_enabled_var.get()
    app.append_transcript_card({"id": "layout", "source_text": "Hola.", "translated_text": "Hello.",
        "source_language": "es", "target_language": "en", "translation_pending": False})
    _, translation, original = app.transcript_targets["layout"]
    children = translation.master.pack_slaves()
    assert children.index(translation) < children.index(original)
    assert translation.cget("fg") == gui.COLORS["text"]
    assert original.cget("fg") == gui.COLORS["secondary"]
