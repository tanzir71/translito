import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import gui


@pytest.fixture(scope="module")
def app(tmp_path_factory, tk_parent):
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
            root = tk.Toplevel(tk_parent)
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


def test_budget_lives_on_engine_and_connect_has_one_provider_picker(app):
    assert not hasattr(app, "cost_budget_entry")
    app.monthly_budget_var.set("5.00")
    assert app.engine_budget_entry.get() == "5.00"
    from provider_settings import open_provider_settings
    window = open_provider_settings(app, gui.COLORS, gui.center_window)
    window.update_idletasks()
    window.provider_var.set("soniox")
    assert window.key_var.get() == ""
    assert not window.winfo_children()[0].winfo_class() == "TNotebook"
    window.destroy()


def test_four_subtitle_entry_points_share_one_state_and_any_pair_text(app):
    controller = app.subtitle_controller
    for origin in ("main", "tray", "hotkey", "settings"):
        controller.set_enabled(False, origin)
        assert not app.subtitles_enabled_var.get()
        controller.set_enabled(True, origin)
        assert app.preferences.get("UI", "subtitles_enabled", False)
    for source, target in (("Hola", "Hello"), ("Hello", "Ù…Ø±Ø­Ø¨Ø§")):
        controller.accept({"id":target,"source_text":source,"translated_text":target,"translation_pending":False})
        assert controller.overlay.entries[-1]["translated_text"] == target


def test_overlay_reply_tray_shares_current_set_and_shortcuts(app):
    from engines.replies import phrasebook
    app.subtitles_enabled_var.set(True)
    app.reply_controller.replies = phrasebook("es","en")
    app.reply_controller.render()
    tray = app.subtitle_controller.overlay.reply_tray
    assert tray.winfo_manager() == "pack"
    assert len(tray.winfo_children()) == 3
    assert {"replies","reply_1","reply_2","reply_3"} <= set(app.hotkey_vars)
    app.reply_controller.options["show_on_overlay"].set(False)
    assert not tray.winfo_manager()


def test_engine_cards_keep_setup_simple_and_checks_live_only_under_models(app):
    app.open_settings()
    texts = []
    def visit(widget):
        if "text" in widget.keys():
            texts.append(str(widget.cget("text")))
        for child in widget.winfo_children():
            visit(child)
    visit(app.root)
    assert not {"Run check", "Check this PC's speed", "Compare engines", "Connect providers"} & set(texts)
    assert "Tools · Compare engines on a sample" in texts
    assert "not measured" not in " ".join(v.get() for v in app.engine_card_descriptions.values())
    app.engine_default_vars["default_asr_model"].set("saved-future-model")
    app.settings_shell.show("Engine")
    assert app.engine_default_vars["default_asr_model"].get() == "saved-future-model"


def test_main_capture_switch_remembers_device_and_app_and_cancels_default_wait(app,monkeypatch):
    from device_utils import InputDeviceChoice
    from engines.process_audio import ProcessSource
    import engines.process_audio
    device = InputDeviceChoice("Headphones",SimpleNamespace(is_process_loopback=False),True,False)
    browser = ProcessSource(10,100,"Chrome",executable="chrome.exe")
    monkeypatch.setattr(gui,"query_input_devices",lambda **kw:[device])
    monkeypatch.setattr(engines.process_audio,"supported",lambda:True)
    monkeypatch.setattr(engines.process_audio,"active_sources",lambda:[ProcessSource(1,1,"All apps",exclude=True),browser])
    app.default_app_var.set("Zoom.exe")
    app.refresh_devices()
    app.capture_kind_buttons["App audio"].invoke()
    app.listen_combo.current(1)
    app.persist_current_listen_device()
    assert app.preferences.get("CAPTURE","app_executable","") == "chrome.exe"
    app._waiting_meeting_app, app._meeting_timer = True,app.root.after(10000,lambda:None)
    app.capture_kind_buttons["Device"].invoke()
    assert not app._waiting_meeting_app and app._meeting_timer is None
    assert app.selected_listen_choice().raw is device.raw
    assert app.preferences.get("CAPTURE","device_name","") == "Headphones"
    app.capture_kind_buttons["App audio"].invoke()
    assert app.selected_listen_choice().raw is browser
    app.root.update_idletasks()
    assert app.root.wm_geometry().split("+")[0] == "800x640"
    assert all(button.winfo_viewable() for button in app.capture_kind_buttons.values())
    assert app.listen_combo.winfo_rooty()+app.listen_combo.winfo_height() == app.listen_source_combo.winfo_rooty()+app.listen_source_combo.winfo_height()
    app.lock_controls(True)
    assert all(str(button.cget("state")) == "disabled" for button in app.capture_kind_buttons.values())
    app.lock_controls(False)
    app.capture_kind_buttons["Device"].invoke()
    app.preferences.set("CAPTURE","app_executable","")
    app.capture_kind_buttons["App audio"].invoke()
    assert app.listen_combo.current() == -1 and "Zoom.exe" in app.listen_combo.get()
    app.capture_kind_buttons["Device"].invoke()
    assert app.preferences.get("CAPTURE","app_executable","") == ""
    app.default_app_var.set("")


def test_every_style_has_dark_interaction_states(app):
    import ast
    from pathlib import Path
    styles = {"TButton", "Treeview.Heading", "Vertical.TScrollbar", "Horizontal.TScrollbar",
              "TCheckbutton", "TRadiobutton"}
    for path in [*Path(".").glob("*.py"), *Path("engines").glob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "style" and isinstance(node.value, ast.Constant):
                styles.add(node.value.value)
    def luminance(color):
        values = [v/65535 for v in app.root.winfo_rgb(color)]
        linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))
    for name in styles:
        for state in ((), ("active",), ("pressed", "active"), ("focus",), ("disabled",)):
            bg = app.style.lookup(name, "background", state)
            fg = app.style.lookup(name, "foreground", state)
            assert bg and luminance(bg) < .35, (name, state, bg)
            if "disabled" not in state and fg:
                bright, dark = sorted((luminance(bg), luminance(fg)), reverse=True)
                assert (bright+.05)/(dark+.05) >= 2.9, (name, state, bg, fg)
    assert app.style.lookup("SegmentActive.TButton", "background", ("active",)) == gui.COLORS["field"]
    assert app.style.lookup("SegmentActive.TButton", "bordercolor", ("focus",)) == gui.COLORS["blue"]
    app.open_settings()
    app.settings_shell._hover("Audio", True)
    assert app.settings_shell.buttons["Audio"].cget("bg") == gui.COLORS["surface_2"]
