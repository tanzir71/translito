import ctypes
import builtins
from datetime import datetime
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import windows_audio


@pytest.mark.parametrize("result,release", [(0, True), (1, True), (-2147417850, False)])
def test_com_reference_is_balanced_on_success_existing_mta_and_existing_sta(monkeypatch, result, release):
    api = SimpleNamespace(CoInitializeEx=Mock(return_value=result), CoUninitialize=Mock())
    monkeypatch.setattr(windows_audio, "_load_com_api", lambda: api)
    with pytest.raises(ValueError, match="recording failed"):
        with windows_audio.audio_com_context():
            api.CoUninitialize.assert_not_called()
            raise ValueError("recording failed")
    api.CoInitializeEx.assert_called_once_with(None, 0)
    assert api.CoUninitialize.call_count == int(release)


def test_com_initialization_failure_never_starts_audio_or_releases_a_reference(monkeypatch):
    api = SimpleNamespace(CoInitializeEx=Mock(return_value=-2147024882), CoUninitialize=Mock())
    monkeypatch.setattr(windows_audio, "_load_com_api", lambda: api)
    with pytest.raises(OSError, match="HRESULT 0x8007000E"):
        with windows_audio.audio_com_context():
            pytest.fail("Audio started after initialization failure")
    api.CoUninitialize.assert_not_called()


def test_audio_context_is_a_noop_without_windows_com(monkeypatch):
    monkeypatch.setattr(windows_audio, "_load_com_api", lambda: None)
    with windows_audio.audio_com_context():
        pass


def test_device_name_lookup_runs_inside_audio_context(monkeypatch):
    import device_utils
    local = threading.local()
    api = SimpleNamespace(CoInitializeEx=lambda *_: setattr(local, "active", True) or 0,
                          CoUninitialize=lambda: setattr(local, "active", False))
    monkeypatch.setattr(windows_audio, "_load_com_api", lambda: api)
    class Microphone:
        isloopback = False
        @property
        def name(self):
            assert local.active
            return "Microphone"
    def enumerate_devices(**kwargs):
        assert local.active
        return [Microphone()]
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_microphones=enumerate_devices))
    original_import = builtins.__import__
    def import_dependency(name, *args, **kwargs):
        if name == "soundcard":
            assert not getattr(local, "active", False)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", import_dependency)
    assert device_utils.query_input_devices()[0].name == "Microphone"
    assert not local.active


def test_self_test_imports_soundcard_before_adding_its_com_reference(monkeypatch):
    import engines.virtual_mic as cable
    local = threading.local()
    api = SimpleNamespace(CoInitializeEx=lambda *_: setattr(local, "active", True) or 0,
                          CoUninitialize=lambda: setattr(local, "active", False))
    monkeypatch.setattr(windows_audio, "_load_com_api", lambda: api)
    def enumerate_devices(**kwargs):
        assert local.active
        return []
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(all_microphones=enumerate_devices))
    original_import = builtins.__import__
    def import_dependency(name, *args, **kwargs):
        if name == "soundcard":
            assert not getattr(local, "active", False)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", import_dependency)
    result = cable.self_test(SimpleNamespace(name="CABLE Input"), sounddevice=SimpleNamespace())
    assert not result.passed and "CABLE Output was not found" in result.message
    assert not local.active


def test_capture_initializes_before_device_access_and_releases_after_failure(monkeypatch):
    import main
    events = []
    local = threading.local()
    api = SimpleNamespace(CoInitializeEx=lambda *_: setattr(local, "active", True) or 0,
                          CoUninitialize=lambda: setattr(local, "active", False))
    monkeypatch.setattr(windows_audio, "_load_com_api", lambda: api)
    class DisconnectedDevice:
        @property
        def name(self):
            assert local.active
            raise OSError("Device disconnected")
    app = main.ArabicAudioTranscriber.__new__(main.ArabicAudioTranscriber)
    app.selected_device = DisconnectedDevice()
    app.running = True
    app.emit = lambda *event: events.append(event)
    app.capture_audio()
    assert not app.running and not local.active
    assert events == [("error", "Audio capture failed: Device disconnected")]


def test_transcript_device_metadata_is_read_inside_audio_context(tmp_path, monkeypatch):
    import main
    local = threading.local()
    api = SimpleNamespace(CoInitializeEx=lambda *_: setattr(local, "active", True) or 0,
                          CoUninitialize=lambda: setattr(local, "active", False))
    monkeypatch.setattr(windows_audio, "_load_com_api", lambda: api)
    class Device:
        @property
        def name(self):
            assert local.active
            return "Test virtual audio"
    app = main.ArabicAudioTranscriber.__new__(main.ArabicAudioTranscriber)
    app.transcripts = [{"timestamp": "2026-11-03T02:00:00", "source_text": "Test", "translated_text": "Test"}]
    app.transcript_folder = tmp_path
    app.session_start_time = datetime(2026, 11, 3, 2)
    app.selected_device = Device()
    app.mode = "listen"
    saved = app.save_transcript()
    assert saved and "Audio Device: Test virtual audio" in Path(saved).read_text(encoding="utf-8")
    assert not local.active


@pytest.mark.skipif(sys.platform != "win32", reason="Windows COM integration")
def test_real_windows_worker_has_an_apartment_only_for_its_audio_scope():
    outcomes, errors = [], []
    def worker():
        try:
            api = ctypes.WinDLL("ole32")
            api.CoGetApartmentType.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
            api.CoGetApartmentType.restype = ctypes.c_long
            def apartment_result():
                apartment, qualifier = ctypes.c_int(), ctypes.c_int()
                return api.CoGetApartmentType(ctypes.byref(apartment), ctypes.byref(qualifier)) & 0xFFFFFFFF
            before = apartment_result()
            with windows_audio.audio_com_context():
                inside = apartment_result()
            outcomes.append((before, inside, apartment_result()))
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(3)
    assert not thread.is_alive() and not errors
    assert len(outcomes) == 1
    before, inside, after = outcomes[0]
    assert inside == 0 and before == after
