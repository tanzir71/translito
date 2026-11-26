"""The real desktop with writes enabled; external integrations are all fakes."""
from pathlib import Path
import time
import tkinter as tk

import pytest

import app_config
import gui


@pytest.fixture
def desktop(tmp_path, monkeypatch, tk_parent):
    monkeypatch.delenv("TRANSLITO_UI_PREVIEW", raising=False)
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **kw: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **kw: None)
    path = tmp_path / "config.ini"
    path.write_text("[CAPTURE]\ndefault_app_prompted = 1\n")
    monkeypatch.setattr(gui, "CONFIG_FILE", path)
    monkeypatch.setattr(app_config, "CONFIG_FILE", path)
    monkeypatch.setattr(gui, "is_open_at_login_enabled", lambda: False)
    monkeypatch.setattr("login.migrate_startup_command", lambda: False)
    monkeypatch.setattr(gui, "query_input_devices", lambda **kw: [])
    monkeypatch.setattr(gui, "query_output_devices", lambda: [])
    for name in ("register_hotkeys", "setup_tray", "refresh_voices", "preload_current_models", "auto_refresh_devices"):
        monkeypatch.setattr(gui.TranslatorGUI, name, lambda self: None)
    apps = []
    def create():
        for previous in apps:
            try:
                exists = previous.root.winfo_exists()
            except tk.TclError:
                exists = False
            if exists:
                previous.download_manager.close()
                previous.preferences.close()
                previous.subtitle_controller.close()
                previous.reply_controller.close()
                previous.root.destroy()
        root = tk.Toplevel(tk_parent)
        root.withdraw()
        app = gui.TranslatorGUI(root)
        from types import SimpleNamespace
        app.credential_store = SimpleNamespace(get=lambda name: None, save=lambda *args: None, delete=lambda *args: None)
        app.open_settings()
        root.update()
        apps.append(app)
        return app
    yield create, path
    for app in apps:
        try:
            exists = app.root.winfo_exists()
        except tk.TclError:
            exists = False
        if exists:
            app.download_manager.close()
            app.preferences.close()
            app.subtitle_controller.close()
            app.reply_controller.close()
            app.root.destroy()


def widgets(parent):
    yield parent
    for child in parent.winfo_children():
        yield from widgets(child)


def edit(app, variable, value):
    name = str(variable)
    matches = []
    for widget in widgets(app.root):
        for option in ("textvariable", "variable"):
            if option in widget.keys() and str(widget.cget(option)) == name:
                matches.append(widget)
    assert matches, name
    widget = matches[-1]
    if widget.winfo_class() in {"TEntry", "Entry"}:
        widget.delete(0, "end")
        widget.insert(0, value)
        widget.event_generate("<FocusOut>")
    elif widget.winfo_class() in {"TCombobox", "Spinbox", "TSpinbox"}:
        widget.set(value)
        widget.event_generate("<<ComboboxSelected>>")
    else:
        variable.set(value)
    app.root.update()


def test_real_controls_round_trip_and_session_reads_canonical_values(desktop):
    create, path = desktop
    first = create()
    edit(first, first.listen_source_var, "Spanish")
    edit(first, first.monthly_budget_var, "$5")
    edit(first, first.quality_var, "Fast")
    edit(first, first.variety_var, "es-MX")
    edit(first, first.schedule_controller.variables["source"], "weekly")
    first.preferences.store.flush()
    first.root.update()
    end = time.monotonic() + .3
    while time.monotonic() < end:
        first.root.update()
        time.sleep(.01)
    assert first.save_status_var.get() == "✓ Saved"
    assert "listen_source =" not in path.read_text()
    second = create()
    assert second.listen_source_var.get() == "Spanish"
    assert second.monthly_budget_var.get() == "5.00"
    assert second.quality_var.get() == "Fast"
    assert second.current_model_request()["src_iso"] == "es"
    assert app_config.load_runtime_config(path).asr_preset == "fast"
    assert app_config.load_language_config(path).source == "es"


def test_invalid_money_helper_and_opening_engine_does_not_overwrite(desktop):
    create, path = desktop
    app = create()
    edit(app, app.monthly_budget_var, "5")
    app.preferences.store.flush()
    before = path.read_bytes()
    edit(app, app.monthly_budget_var, "five")
    assert app.monthly_budget_var.validation_error.get() == "Enter an amount like 5 or 12.50"
    app.preferences.store.flush()
    assert path.read_bytes() == before
    app.engine_default_vars["default_asr_model"].set("saved-model-not-in-current-list")
    app.preferences.store.flush()
    app.settings_shell.show("Engine")
    assert app.engine_default_vars["default_asr_model"].get() == "saved-model-not-in-current-list"


def test_speak_controls_restart_with_the_same_runtime_devices_and_voice(desktop, monkeypatch):
    from device_utils import InputDeviceChoice, OutputDeviceChoice
    from types import SimpleNamespace
    inputs = [InputDeviceChoice(name, SimpleNamespace(), False, False) for name in ("First mic", "USB mic")]
    outputs = [OutputDeviceChoice("Speakers", 0, False), OutputDeviceChoice("CABLE Input", 1, True)]
    monkeypatch.setattr(gui, "query_input_devices", lambda **kw: inputs)
    monkeypatch.setattr(gui, "query_output_devices", lambda: outputs)
    create, path = desktop
    first = create()
    edit(first, first.listen_source_var, "Spanish")
    edit(first, first.listen_target_var, "French")
    edit(first, first.speak_mic_var, inputs[1].display_name)
    edit(first, first.speak_output_var, outputs[1].display_name)
    edit(first, first.speak_source_var, "English")
    edit(first, first.speak_target_var, "Spanish")
    first.voice_settings_combo.configure(values=("Automatic", "Spanish voice"))
    edit(first, first.voice_var, "Spanish voice")
    edit(first, first.monitor_var, True)
    first.preferences.store.flush()
    second = create()
    speak = app_config.load_speak_config(path)
    assert (speak.mic_name, speak.output_device_name, speak.voice) == ("USB mic", "CABLE Input", "Spanish voice")
    assert (speak.source, speak.target, speak.monitor_spoken_audio) == ("en", "es", True)
    assert second.selected_speak_mic_choice().name == speak.mic_name
    assert second.selected_output_choice().name == speak.output_device_name
    assert second.voice_var.get() == speak.voice
    second._apply_voices(["Automatic"])
    second.preferences.store.flush()
    assert app_config.load_speak_config(path).voice == "Spanish voice"
    # A temporarily disconnected device may change the displayed fallback only.
    monkeypatch.setattr(gui, "query_input_devices", lambda **kw: inputs[:1])
    second.refresh_devices()
    second.preferences.store.flush()
    assert app_config.load_speak_config(path).mic_name == "USB mic"


def test_inline_connect_status_and_remove_during_background_download(desktop, monkeypatch):
    from types import SimpleNamespace
    from engines.cloud_connect import CloudConnector
    import httpx
    import cloud_ui
    create, path = desktop
    app = create()
    keys, requests = {}, []
    fake_store = SimpleNamespace(get=keys.get, save=lambda p,k: keys.update({p:k}), delete=lambda p: keys.pop(p, None))
    def response(request):
        requests.append(request)
        return httpx.Response(200, json={})
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        controller = CloudConnector(path, fake_store, client=client)
        monkeypatch.setattr(cloud_ui, "CloudConnector", lambda *a, **kw: controller)
        app.credential_store = fake_store
        app.engine_choice_var.set("cloud")
        app.cloud_key_var.set("mock-only-7f3a")
        app.cloud_connect_button.invoke()
        end = time.monotonic() + 3
        while "Connected to Soniox" not in app.cloud_connection_status.get() and time.monotonic() < end:
            app.root.update()
            time.sleep(.01)
        assert "Connected to Soniox" in app.cloud_connection_status.get()
        assert "Key ending 7f3a" in app.cloud_connection_status.get()
        assert app.cloud_key_var.get() == ""
        assert len(requests) == 1 and not requests[0].content
        assert not app.model_setup_busy
        assert str(app.listen_action_button.cget("state")) == "normal"
        assert app.engine_var.get() == "On this PC · needs a monthly budget"
        app.cloud_remove()
        assert not keys


def test_workday_chips_times_validation_and_restart(desktop, monkeypatch):
    from engines.weekly_schedule import PRESETS
    from app_config import read_config
    import json
    monkeypatch.setattr("engines.weekly_schedule.local_timezone", lambda: "Asia/Dhaka")
    create, path = desktop
    first = create()
    first.settings_shell.show("Schedule")
    first.schedule_block_views[0]["preset"](PRESETS["Sun–Thu"])
    first.root.update()
    var, widget = first.schedule_block_views[0]["times"]["start"]
    widget.set("9:30 pm")
    widget.event_generate("<FocusOut>")
    var, widget = first.schedule_block_views[0]["times"]["end"]
    widget.set("06:00")
    widget.event_generate("<FocusOut>")
    first.preferences.store.flush()
    saved = json.loads(read_config(path)["SCHEDULE"]["weekly_blocks"])
    assert saved[0]["days"] == [0,1,2,3,6]
    assert saved[0]["start"] == "21:30" and saved[0]["end"] == "06:00"
    assert "ends the next day" in first.schedule_block_views[0]["summary"].get()
    before = path.read_bytes()
    widget.set("bad time")
    widget.event_generate("<FocusOut>")
    first.preferences.store.flush()
    assert "Enter a time" in first.schedule_error_var.get()
    assert path.read_bytes() == before
    second = create()
    assert json.loads(second.schedule_controller.variables["weekly_blocks"].get()) == saved
    second.schedule_add_block()
    assert str(second.schedule_block_views[1]["days"][0].cget("state")) == "disabled"
    assert second.schedule_block_views[1]["days"][0].tooltip


def test_weekly_utc_notice_is_migrated_once_and_tray_start_is_quiet(desktop, monkeypatch):
    import json
    from unittest.mock import Mock
    from app_config import read_config
    monkeypatch.setattr("engines.weekly_schedule.local_timezone", lambda: "Asia/Dhaka")
    monkeypatch.setattr(gui.sys, "argv", ["gui.py", "--tray"])
    tray = Mock()
    monkeypatch.setattr(gui.TranslatorGUI, "setup_tray", tray)
    create, path = desktop
    old = [dict(weekday=d,start="09:30",end="18:00",timezone="UTC") for d in range(5)]
    path.write_text("[CAPTURE]\ndefault_app_prompted = 1\n[SCHEDULE]\ntimezone = UTC\nweekly_times = "+json.dumps(old)+"\n")
    app = create()
    assert app.root.state() == "withdrawn"
    tray.assert_called_once()
    assert "Weekly times now use your PC's time zone (Asia/Dhaka)" in app.hint_var.get()
    assert read_config(path).get("SCHEDULE","timezone_notice") == ""
    next_app = create()
    assert "Weekly times now use" not in next_app.hint_var.get()
