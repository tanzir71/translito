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
        assert app.cloud_connect_button.cget("text") == "Check connection"
        assert app.cloud_remove_button.winfo_manager() == "pack"
        assert len(requests) == 1 and not requests[0].content
        assert not app.model_setup_busy
        assert str(app.listen_action_button.cget("state")) == "normal"
        assert app.engine_var.get() == "On this PC · needs a monthly budget"
        from engines.settings import load_engine_settings
        settings = load_engine_settings(path)
        assert settings.default_asr_provider == settings.default_mt_provider == "soniox"
        # Rechecking an existing key must preserve an intentional advanced route.
        app.engine_default_vars["default_mt_provider"].set("deepl")
        app.engine_default_vars["default_mt_model"].set("custom-translation")
        app.cloud_connect_button.invoke()
        end = time.monotonic() + 3
        while (len(requests) < 2 or "Connecting" in app.cloud_connection_status.get()) and time.monotonic() < end:
            app.root.update()
            time.sleep(.01)
        assert len(requests) == 2
        settings = load_engine_settings(path)
        assert settings.default_mt_provider == "deepl" and settings.default_mt_model == "custom-translation"
        app.cloud_remove()
        assert not keys
        assert app.cloud_connect_button.cget("text") == "Connect"
        assert not app.cloud_remove_button.winfo_manager()


def test_advanced_connection_activates_complete_soniox_route(desktop, monkeypatch):
    from types import SimpleNamespace
    from engines.cloud_connect import CloudConnector
    from engines.settings import load_engine_settings
    import httpx
    import provider_settings
    create, path = desktop
    app = create()
    keys = {}
    store = SimpleNamespace(get=keys.get, save=lambda p, k: keys.update({p: k}), delete=lambda p: keys.pop(p, None))
    app.credential_store = store
    app.engine_default_vars["default_asr_provider"].set("elevenlabs")
    app.engine_default_vars["default_mt_provider"].set("deepl")
    chooser = next(w for w in widgets(app.settings_window) if w.winfo_class() == "TCombobox"
                   and str(w.cget("textvariable")) == str(app.cloud_provider_var))
    app.cloud_provider_var.set(next(v for v in chooser.cget("values") if v.startswith("ElevenLabs")))
    chooser.event_generate("<<ComboboxSelected>>")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))) as client:
        connection = CloudConnector(path, store, client=client)
        monkeypatch.setattr(provider_settings, "CloudConnector", lambda *a, **kw: connection)
        window = app.open_provider_settings()
        window.provider_var.set("soniox")
        window.key_var.set("mock-advanced-soniox")
        button = next(w for w in widgets(window) if w.winfo_class() == "TButton" and w.cget("text") == "Connect")
        button.invoke()
        end = time.monotonic() + 3
        while load_engine_settings(path).default_mt_provider != "soniox" and time.monotonic() < end:
            app.root.update()
            time.sleep(.01)
        settings = load_engine_settings(path)
        assert settings.default_asr_provider == settings.default_mt_provider == "soniox"
        assert app.engine_default_vars["default_asr_provider"].get() == "soniox"
        assert app.engine_default_vars["default_mt_model"].get() == "automatic"
        assert app.cloud_provider_var.get().startswith("Soniox")
        window.destroy()


def test_empty_state_actions_share_one_row_and_equal_size(desktop):
    create, _ = desktop
    app = create()
    app.root.deiconify()
    app.root.update()
    actions = {widget.cget("text"): widget for widget in widgets(app.empty_state)
               if widget.winfo_class() == "TButton"}
    cloud, local = actions["Set up cloud"], actions["Keep using this PC"]
    assert cloud.master is local.master
    assert cloud.winfo_y() == local.winfo_y()
    assert cloud.winfo_width() == local.winfo_width() > 1
    assert cloud.winfo_height() == local.winfo_height() > 1
    assert cloud.winfo_x() + cloud.winfo_width() < local.winfo_x()


def test_single_empty_state_action_is_centered_and_pair_layout_restores(desktop):
    from dataclasses import replace
    from engines.session_state import ReadinessState
    create, _ = desktop
    app = create()
    app.root.deiconify()
    controller = app.session_controller
    plan = controller.plan
    for offer in (False, True, False):
        app.preferences.set("UI", "setup_offer_seen", not offer)
        controller.plan = replace(plan, preferred_engine="local" if offer else "cloud")
        controller.state = ReadinessState("setup_required", "Connect cloud to use this route.", "connect")
        controller.render()
        app.root.update_idletasks()
        cloud, local = app.empty_setup_button, app.empty_local_button
        row = app.empty_actions
        assert abs(row.winfo_rootx() + row.winfo_width() / 2 -
                   (app.empty_state.winfo_rootx() + app.empty_state.winfo_width() / 2)) <= 1
        if offer:
            assert local.winfo_ismapped()
            assert cloud.winfo_width() == local.winfo_width()
            assert cloud.winfo_height() == local.winfo_height()
            assert cloud.winfo_y() == local.winfo_y()
        else:
            assert not local.winfo_ismapped()
            assert abs(cloud.winfo_rootx() + cloud.winfo_width() / 2 -
                       (row.winfo_rootx() + row.winfo_width() / 2)) <= 1


def test_launch_opens_listen_even_after_speak_and_toggle_uses_current_tab(desktop, monkeypatch):
    from unittest.mock import Mock
    create, path = desktop
    first = create()
    first.set_mode("speak")
    first.speak_source_var.set("Spanish")
    first.preferences.store.flush()
    assert app_config.load_runtime_config(path).last_mode == "speak"
    app = create()
    assert app.mode_var.get() == "listen"
    assert app.listen_frame.winfo_manager() == "grid"
    assert not app.speak_frame.winfo_manager()
    assert app.speak_source_var.get() == "Spanish"
    start = Mock()
    monkeypatch.setattr(app, "start", start)
    app.hotkey_toggle()
    assert app.mode_var.get() == "listen"
    start.assert_called_once()


def test_cloud_ready_has_start_and_no_repeated_setup_offer(desktop, monkeypatch):
    from dataclasses import replace
    from decimal import Decimal
    from types import SimpleNamespace
    import session_ui
    from engines.session_state import resolve_plan
    from engines.model_files import Ready, Missing
    from engines.settings import EngineSettings, ProviderSettings, credential_signature, save_engine_settings
    create, path = desktop
    app = create()
    key = "fake-key-only"
    pref = ProviderSettings(enabled=True, monthly_cap=Decimal(5), account_kind="paid")
    pref = replace(pref, tested_signature=credential_signature("soniox", key, pref))
    save_engine_settings(EngineSettings(engine_choice="cloud", monthly_cap=Decimal(5), providers={"soniox": pref}), path)
    app.credential_store = SimpleNamespace(get=lambda _: key)
    app.engine_choice_var.set("cloud")
    monkeypatch.setattr(session_ui, "resolve_plan", lambda *a, **kw: resolve_plan(*a, **kw,
        inspect=lambda spec: Ready(path.parent) if "whisper" in spec.repo.lower() else Missing()))
    app.selected_listen_choice = lambda: SimpleNamespace(name="Saved device")
    app.session_controller.reset_connection()
    end = time.monotonic() + 2
    while app.session_controller.checking and time.monotonic() < end:
        app.root.update()
        time.sleep(.01)
    app.session_controller.refresh()
    assert app.listen_action_button.cget("text") == "Start"
    assert not app.empty_actions.winfo_manager()
    assert app.engine_var.get() == "Soniox"
    request = app.current_model_request()
    assert request["whisper_model"] == "openai/whisper-base"
    assert request["cloud_translation"] and request["translation_model"] == "cloud:ar:en"
    # Navigation does not mutate a selected engine.
    app.session_controller.open_action("engine")
    assert app.engine_choice_var.get() == "cloud"


def test_money_edits_are_pending_until_valid_commit(desktop):
    from engines.settings import load_engine_settings
    create, path = desktop
    app = create()
    app.preferences.set("ENGINES", "monthly_cap_usd", "12")
    app.monthly_budget_var.set("")
    assert load_engine_settings(path).monthly_cap == 12
    assert not app.preferences.commit_pending()
    assert load_engine_settings(path).monthly_cap == 12
    app.monthly_budget_var.set("7.")
    assert not app.preferences.commit_pending()
    assert load_engine_settings(path).monthly_cap == 12
    app.monthly_budget_var.set("7.50")
    assert load_engine_settings(path).monthly_cap == 12
    assert app.preferences.commit_pending()
    assert load_engine_settings(path).monthly_cap == 7.5


def test_active_pair_and_stale_start_tokens_follow_mode_and_language(desktop):
    create, _ = desktop
    app = create()
    app.one_way_var.set(True)
    app.listen_source_var.set("Spanish")
    app.listen_target_var.set("English")
    app.session_controller.refresh()
    assert app.session_controller.plan.pair == ("es", "en")
    old = app.session_controller.begin()
    app.listen_source_var.set("French")
    app.session_controller.refresh()
    assert not app.session_controller.accepts(old)
    app.set_mode("speak")
    app.speak_source_var.set("English")
    app.speak_target_var.set("Japanese")
    app.session_controller.refresh()
    assert app.session_controller.plan.pair == ("en", "ja")
    from engine_ui import pair
    assert pair(app) == ("en", "ja")


def test_main_download_progress_and_controls_share_current_job(desktop):
    from engines.downloads import DownloadJob
    create, path = desktop
    app = create()
    app.download_manager.closed = True
    job = DownloadJob("progress", "fake/progress", "Lite translation · es → en", str(path.parent),
                      bytes=50, total=100, state="Downloading")
    app.download_manager.enqueue(job)
    assert "50%" in app.download_text.get()
    assert app.download_progress.cget("value") == .5
    app.download_pause.invoke()
    assert job.state == "Paused" and app.download_pause.cget("text") == "Resume"
    app.download_pause.invoke()
    assert job.state == "Queued" and job.bytes == 50
    app.download_cancel.invoke()
    assert job.state == "Cancelled" and job.bytes == 50
    assert app.download_current is None and not app.download_panel.winfo_manager()


def test_cancel_dismisses_failed_download_and_its_warning(desktop):
    from engines.downloads import DownloadJob
    create, path = desktop
    app = create()
    app.download_manager.closed = True
    job = DownloadJob("cancel-error", "fake/cancel", "Failed", str(path.parent / "missing"),
                      state="Paused", pause_reason="failure", error="Cache check failed", error_code="check_cache:OSError")
    app.download_manager.enqueue(job)
    assert app.hint_var.get() == "Cache check failed"
    app.download_cancel.invoke()
    assert job.state == "Cancelled" and not job.error and not job.error_code
    assert app.download_current is None and not app.download_panel.winfo_manager()
    assert not app.hint_var.get() and not app.hint_frame.winfo_manager()


def test_browsing_unconnected_provider_keeps_soniox_start_ready(desktop, monkeypatch):
    from dataclasses import replace
    from decimal import Decimal
    from types import SimpleNamespace
    import cloud_ui, session_ui
    from engines.cloud_connect import CloudConnector
    from engines.model_files import Ready
    from engines.session_state import resolve_plan
    from engines.settings import EngineSettings, ProviderSettings, credential_signature, save_engine_settings, load_engine_settings
    create, path = desktop
    app = create()
    key = "fake-soniox-only"
    pref = ProviderSettings(enabled=True, monthly_cap=Decimal(2), account_kind="paid")
    pref = replace(pref, tested_signature=credential_signature("soniox", key, pref))
    save_engine_settings(EngineSettings(profile="custom", engine_choice="cloud", monthly_cap=Decimal(2),
        providers={"soniox": pref}, default_asr_provider="soniox", default_mt_provider="soniox"), path)
    store = SimpleNamespace(get=lambda name: key if name == "soniox" else None)
    app.credential_store = store
    controller = CloudConnector(path, store)
    monkeypatch.setattr(cloud_ui, "CloudConnector", lambda *a, **kw: controller)
    monkeypatch.setattr(session_ui, "resolve_plan", lambda *a, **kw: resolve_plan(*a, **kw, inspect=lambda _: Ready(path.parent)))
    app.selected_listen_choice = lambda: SimpleNamespace(name="Saved source")
    app.engine_choice_var.set("cloud")
    app.monthly_budget_var.set("2")
    app.preferences.commit_pending()
    app.refresh_cloud_connection()
    end = time.monotonic() + 2
    while app.session_controller.checking and time.monotonic() < end:
        app.root.update(); time.sleep(.01)
    app.session_controller.reset_connection()
    end = time.monotonic() + 2
    while app.session_controller.checking and time.monotonic() < end:
        app.root.update(); time.sleep(.01)
    chooser = next(widget for widget in widgets(app.settings_window) if widget.winfo_class() == "TCombobox"
                   and str(widget.cget("textvariable")) == str(app.cloud_provider_var))
    for name in ("ElevenLabs", "Speechmatics"):
        label = next(value for value in chooser.cget("values") if value.startswith(name))
        app.cloud_provider_var.set(label)
        chooser.event_generate("<<ComboboxSelected>>")
        app.root.update()
        settings = load_engine_settings(path)
        assert settings.default_asr_provider == settings.default_mt_provider == "soniox"
        assert app.session_controller.plan.asr == app.session_controller.plan.mt == "soniox"
        assert app.listen_action_button.cget("text") == "Start"
        assert app.session_controller.state.can_start


def test_startup_does_not_replay_failed_download_warning_and_resume_clears_fresh_warning(desktop, monkeypatch):
    from dataclasses import asdict
    import json
    from engines.downloads import DownloadJob
    create, path = desktop
    directory = path.parent / "downloads"
    directory.mkdir()
    job = DownloadJob("saved-failure", "fake/missing", "Missing", str(path.parent / "missing"),
                      state="Paused", pause_reason="failure", error="Old download failure")
    (directory / "saved-failure.json").write_text(json.dumps(asdict(job)))
    app = create()
    app.download_manager.closed = True
    restored = app.download_manager.jobs[0]
    assert "Old download failure" not in app.hint_var.get()
    calls = []
    show_hint = app.show_hint
    monkeypatch.setattr(app, "show_hint", lambda message: (calls.append(message), show_hint(message)))
    app.download_manager.resume(restored)
    restored.state, restored.pause_reason, restored.error = "Paused", "failure", "New download failure"
    app.download_manager.on_change(restored)
    app.download_manager.on_change(restored)
    assert calls.count("New download failure") == 1
    app.download_manager.resume(restored)
    assert app.hint_var.get() == "" and not app.hint_frame.winfo_manager()


def test_stop_during_startup_discards_late_transcriber(desktop, monkeypatch):
    import threading
    from types import SimpleNamespace
    from unittest.mock import Mock
    import session_ui
    from engines.model_files import Ready
    from engines.session_state import resolve_plan
    create, path = desktop
    app = create()
    app.listen_source_type_var.set("Device")
    monkeypatch.setattr(session_ui, "resolve_plan", lambda *a, **kw: resolve_plan(*a, **kw, inspect=lambda _: Ready(path.parent)))
    monkeypatch.setattr("engines.model_files.missing_translations", lambda *a: [])
    app.selected_listen_choice = lambda: SimpleNamespace(name="Test source", raw=SimpleNamespace())
    entered, release = threading.Event(), threading.Event()
    child = Mock()
    def construct(**kw):
        entered.set()
        release.wait(3)
        kw["on_event"]("hint", "Stale startup must not appear")
        return child
    monkeypatch.setattr(gui, "ArabicAudioTranscriber", construct)
    assert app.start() == "pending"
    assert entered.wait(2)
    app.stop()
    release.set()
    end = time.monotonic() + 1
    while not child.stop_background.called and time.monotonic() < end:
        app.root.update()
        time.sleep(.01)
    assert app.transcriber is None and not app.model_setup_busy
    child.stop_background.assert_called_once()
    child.start_background.assert_not_called()


def test_download_notification_cannot_stop_a_meeting(desktop, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    create, _ = desktop
    app = create()
    monkeypatch.setattr(app, "stop", Mock())
    app.schedule_controller.toast(SimpleNamespace(title="Lite is ready", download=True))
    app.root.update_idletasks()
    choices = [w for w in widgets(app.root) if w.winfo_class() == "TButton" and w.cget("text") == "Dismiss"]
    assert len(choices) == 1
    notice = choices[0].winfo_toplevel()
    assert {w.cget("text") for w in widgets(notice) if w.winfo_class() == "TButton"} == {"Dismiss", "Models"}
    choices[0].invoke()
    app.stop.assert_not_called()


def test_repeated_stop_does_not_overlap_shutdown_or_save(desktop):
    import threading
    from unittest.mock import Mock
    create, _ = desktop
    app = create()
    release = threading.Event()
    child = Mock(last_saved_path=None)
    child.join_background.side_effect = lambda: release.wait(2)
    child.save_transcript.return_value = None
    app.transcriber = child
    app.stop()
    app.stop()
    child.stop_background.assert_called_once()
    assert app.listen_action_button.cget("text") == "Stopping…"
    assert str(app.listen_action_button.cget("state")) == "disabled"
    release.set()
    end = time.monotonic() + 1
    while app.transcriber is not None and time.monotonic() < end:
        app.root.update()
        time.sleep(.01)
    assert app.transcriber is None
    child.save_transcript.assert_called_once()


def test_local_language_filter_is_opt_in_and_explicit_choice_survives(desktop):
    create, path = desktop
    app = create()
    assert app.skip_other_languages_var.get() is False
    app.skip_other_languages_var.set(True)
    assert app.preferences.commit_pending()
    app = create()
    assert app.skip_other_languages_var.get() is True


def test_first_streaming_row_without_language_renders_translation_subtitles_and_stop(desktop, monkeypatch):
    from unittest.mock import Mock
    from subtitle_overlay import PreviewBackend
    create, _ = desktop
    app = create()
    errors = Mock()
    monkeypatch.setattr(app.root._root(), 'report_callback_exception', errors)
    app.subtitle_controller.backend = PreviewBackend()
    app.subtitles_enabled_var.set(True)
    child = Mock(last_saved_path=None)
    child.save_transcript.return_value = None
    app.transcriber = child
    draft = dict(id='first-live-row', source_text='', translated_text='', source_language=None,
                 target_language='en', mode='listen', translation_pending=True)
    source = dict(draft, source_text='مرحبا.', source_language='ar', language_tag='ar')
    target = dict(source, translated_text='Hello.', translation_pending=False)
    for kind, entry in [('transcript', draft), ('transcript_update', source), ('transcript_update', target)]:
        app.on_event(kind, entry)
    end = time.monotonic() + 2
    while (not app.transcript_entries or not app.transcript_entries[0].get('translated_text')) and time.monotonic() < end:
        app.root.update()
        time.sleep(.01)
    assert len(app.transcript_entries) == 1
    assert app.transcript_entries[0]['translated_text'] == 'Hello.'
    _, translated, original = app.transcript_targets[draft['id']]
    assert translated.cget('text') == 'Hello.' and translated.winfo_manager()
    assert original._language_label.cget('text') == 'AR'
    app.subtitle_controller.tick(schedule=False)
    assert any(label.cget('text') == 'Hello.' for label in app.subtitle_controller.overlay.labels)
    started = time.monotonic()
    app.stop()
    while app.transcriber is not None and time.monotonic() - started < 1.5:
        app.root.update()
        time.sleep(.01)
    assert app.transcriber is None and not app._stopping and app.current_status == 'Ready'
    assert app.listen_action_button.cget('text') != 'Stopping…'
    errors.assert_not_called()


def test_ui_callback_error_does_not_stop_following_events_or_future_ticks(desktop, monkeypatch):
    from unittest.mock import Mock
    create, _ = desktop
    app = create()
    errors = Mock()
    monkeypatch.setattr(app.root._root(), 'report_callback_exception', errors)
    handled = []
    def broken():
        raise ValueError('Deliberate callback failure')
    app.post_ui(broken)
    app.post_ui(lambda: handled.append('same tick'))
    app._drain_ui()
    assert handled == ['same tick']
    assert errors.call_args.args[0] is ValueError
    app.post_ui(lambda: handled.append('next tick'))
    end = time.monotonic() + 1
    while len(handled) < 2 and time.monotonic() < end:
        app.root.update()
        time.sleep(.01)
    assert handled == ['same tick', 'next tick']


@pytest.mark.parametrize('failure_stage', ['cleanup', 'save'])
def test_stop_cleanup_failure_always_returns_control_and_retains_transcript(desktop, failure_stage):
    import threading
    from unittest.mock import Mock
    create, _ = desktop
    app = create()
    child = Mock(last_saved_path=None, _stop_event=threading.Event())
    if failure_stage == 'cleanup':
        child.stop_background.side_effect = OSError('Simulated cleanup failure')
    else:
        child.save_transcript.side_effect = RuntimeError('Simulated COM save failure')
    child.save_transcript.return_value = None
    app.transcriber = child
    app.stop()
    assert child._stop_event.is_set()
    end = time.monotonic() + 2
    while app.transcriber is not None and time.monotonic() < end:
        app.root.update()
        time.sleep(.01)
    assert not app._stopping and app.transcriber is None
    assert app.last_transcriber is child
    assert 'transcript is retained' in app.hint_var.get() or 'Transcript kept in memory' in app.hint_var.get()
    child.save_transcript.assert_called_once()


def test_speak_selects_available_cable_and_only_shows_setup_when_needed(desktop, monkeypatch):
    from device_utils import OutputDeviceChoice
    from engines.virtual_mic import CableTestResult
    outputs = [OutputDeviceChoice("Speakers", 0, False)]
    monkeypatch.setattr(gui, "query_output_devices", lambda: outputs)
    create, _ = desktop
    app = create()
    app.set_mode("speak")
    setup = app.virtual_mic_setup
    assert setup.frame.winfo_manager() == "grid"
    assert setup.frame.cget("bg") == gui.COLORS["surface"]
    outputs.append(OutputDeviceChoice("CABLE Input", 1, True))
    app.refresh_devices()
    assert app.selected_output_choice().name == "CABLE Input"
    assert not setup.frame.winfo_manager()
    # An explicit selection is retained during device polling.
    app.speak_output_combo.current(0)
    app.speak_output_selected()
    app.refresh_devices()
    assert app.selected_output_choice().name == "Speakers"
    app.set_mode("listen")
    app.set_mode("speak")
    assert app.selected_output_choice().name == "CABLE Input"
    assert not setup.frame.winfo_manager()
    app.show_virtual_mic_setup()
    assert setup.frame.winfo_manager() == "grid"
    assert setup.frame.cget("bg") == gui.COLORS["surface"]
    assert not setup.install_button.winfo_manager()
    setup.force_visible = False
    setup.test_result(outputs[1], CableTestResult(False, -70, "Test route failed"))
    assert setup.frame.winfo_manager() == "grid"
    assert setup.frame.cget("bg") == gui.COLORS["yellow_bg"]
    setup.test_result(outputs[1], CableTestResult(True, -15, "Virtual microphone passed."))
    assert not setup.frame.winfo_manager()


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
