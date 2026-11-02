"""Exercise GUI Start with no Tk window, models, driver, audio, or user writes."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import gui
from engines.virtual_mic import CableTestResult


def value(item):
    return SimpleNamespace(get=lambda: item)


def start_fixture(monkeypatch, output_name="CABLE Input (VB-Audio)"):
    host = gui.TranslatorGUI.__new__(gui.TranslatorGUI)
    host.transcriber, host.model_setup_busy = None, False
    host.preview_mode, host._initializing = True, False
    host.root = SimpleNamespace(after=lambda _, callback: callback())
    request = {"mode": "speak", "src_iso": "en", "tgt_iso": "ar", "src_bcp47": "en-US",
               "translation_model": "local", "conversation": None}
    host.current_model_request = lambda: request
    host.configure_offline_env = host.persist_settings = host.hide_banners = Mock()
    host.engine_label = SimpleNamespace(configure=Mock())
    host.noise_gate_var, host.chunk_duration_var = value(.002), value(6)
    host.voice_var, host.monitor_var, host.quality_var = value("Automatic"), value(False), value("Balanced")
    host.transcript_folder_var = value("unused")
    host.selected_speak_mic_choice = lambda: SimpleNamespace(name="real mic", raw="mic")
    output = SimpleNamespace(name=output_name, is_virtual=output_name.startswith("CABLE"))
    host.selected_output_choice = lambda: output
    host.virtual_mic_setup = SimpleNamespace(test_result=Mock())
    host.lock_controls = host.set_status = host.update_action_button = host.show_hint = Mock()
    host.show_virtual_mic_setup = Mock()
    host.update_routing_banner = Mock()
    host.show_error = Mock()
    host.on_event = Mock()
    host.phase_var = SimpleNamespace(set=Mock())
    host.progress = SimpleNamespace(stop=Mock(), grid_remove=Mock())
    host.phase_label = SimpleNamespace(grid_remove=Mock())
    host.level_frame = SimpleNamespace(grid=Mock())
    model = Mock()
    constructed = Mock(return_value=model)
    monkeypatch.setattr(gui, "ArabicAudioTranscriber", constructed)
    return host, model, constructed, output


@pytest.mark.parametrize("passed", [False, True])
def test_each_speak_start_tests_the_route_before_any_model_or_capture(monkeypatch, passed):
    host, model, constructed, output = start_fixture(monkeypatch)
    finished = threading.Event()
    result = CableTestResult(passed, -15 if passed else -70, "test result")
    def test_route(actual):
        assert actual is output
        assert host.model_setup_busy
        constructed.assert_not_called()
        return result
    monkeypatch.setattr("engines.virtual_mic.self_test", test_route)
    failed = host.start_failed
    def failed_and_finish(error):
        failed(error)
        finished.set()
    host.start_failed = failed_and_finish
    model.start_background.side_effect = lambda **kwargs: finished.set()
    host.start()
    assert finished.wait(2)
    assert not host.model_setup_busy
    host.virtual_mic_setup.test_result.assert_called_once_with(output, result)
    if passed:
        constructed.assert_called_once()
        assert host.transcriber is model
    else:
        constructed.assert_not_called()
        model.start_background.assert_not_called()
        assert host.transcriber is None
        host.show_error.assert_called_once_with("test result")


def test_missing_cable_never_tests_a_real_speaker_or_starts_capture(monkeypatch):
    host, model, constructed, output = start_fixture(monkeypatch, "Speakers")
    test = Mock()
    monkeypatch.setattr("engines.virtual_mic.self_test", test)
    host.start()
    constructed.assert_not_called()
    test.assert_not_called()
    host.show_virtual_mic_setup.assert_called_once()
    assert not host.model_setup_busy


def test_forced_hotkey_mode_change_cannot_race_preflight_or_driver_setup():
    host = gui.TranslatorGUI.__new__(gui.TranslatorGUI)
    host.model_setup_busy = True
    host.transcriber = None
    host.mode_var = SimpleNamespace(set=Mock())
    host.set_mode("listen", force=True)
    host.mode_var.set.assert_not_called()
