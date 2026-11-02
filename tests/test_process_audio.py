import ctypes
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from engines.process_audio import ProcessAudioError, ProcessRecorder, ProcessSource, active_sources


def process(pid, name, parents=()):
    return SimpleNamespace(pid=pid, name=lambda: name, create_time=lambda: float(pid), parents=lambda: list(parents))


def test_active_picker_groups_browser_children_and_excludes_our_tree():
    own = process(1, "Translito.exe")
    child = process(2, "powershell.exe", [own])
    root = process(3, "chrome.exe")
    utility = process(4, "chrome.exe", [root])
    renderer = process(5, "chrome.exe", [root])
    zoom = process(6, "Zoom.exe")
    values = {item.pid: item for item in [own, child, root, utility, renderer, zoom]}
    sources = active_sources(bridge=SimpleNamespace(pids=lambda: [1, 2, 4, 5, 6, 99]),
                             process_factory=values.__getitem__, own_pid=1)
    assert [(s.pid, s.exclude) for s in sources] == [(1, True), (3, False), (6, False)]
    assert sources[0].name == "All apps (exclude Translito)"


def test_pid_reuse_and_unsupported_rate_never_open_capture():
    source = ProcessSource(3, 3., "chrome.exe")
    source.validate(process_factory=lambda pid: process(pid, "chrome.exe"))
    with pytest.raises(ProcessAudioError, match="closed or restarted"):
        source.validate(process_factory=lambda pid: process(7, "chrome.exe"))
    with pytest.raises(ProcessAudioError, match="48000"):
        source.recorder(samplerate=16000, bridge=Mock())


class Bridge:
    def __init__(self, code=0, silent=False):
        self.stopped = threading.Event()
        self.closed = False
        self.code, self.silent = code, silent
    def create_stop(self):
        return 42
    def stop(self, handle):
        assert handle == 42
        self.stopped.set()
    def close(self, handle):
        assert handle == 42
        self.closed = True
    def run(self, source, handle, callback):
        assert source.pid == 123 and source.exclude
        if self.code < 0:
            return self.code
        callback(None, 0, None)
        if not self.silent:
            data = (ctypes.c_short * 12)(*range(12))
            callback(data, 6, None)
            # The bridge buffer is borrowed only until the callback returns.
            data[0] = 30000
            callback(None, 2, None)
        assert self.stopped.wait(3)
        return 0


def test_native_pcm_is_copied_split_and_cleared_with_stop():
    bridge = Bridge()
    source = ProcessSource(123, 1, "All apps", exclude=True)
    with ProcessRecorder(source, bridge) as recorder:
        assert np.array_equal(recorder.record(4), np.arange(8, dtype=np.float32).reshape(-1, 2) / 32768)
        tail = recorder.record(4)
        assert np.array_equal(tail[:2], np.arange(8, 12, dtype=np.float32).reshape(-1, 2) / 32768)
        assert not tail[2:].any()
    assert bridge.closed and recorder.ended.is_set()
    assert recorder.pending.size == 0 and recorder.blocks.empty()


def test_silent_source_returns_bounded_silence_and_start_error_releases_handle():
    source = ProcessSource(123, 1, "All apps", exclude=True)
    bridge = Bridge(silent=True)
    with ProcessRecorder(source, bridge) as recorder:
        assert not recorder.record(480).any()
    assert bridge.closed
    bad = Bridge(code=-1)
    with pytest.raises(ProcessAudioError, match="capture failed"):
        with ProcessRecorder(source, bad):
            pytest.fail("Native startup failure must not enter the recording loop")
    assert bad.closed


def test_packaged_bridge_pins_its_current_source_and_binary():
    root = Path(__file__).resolve().parents[1]
    directory = root / "engines" / "data" / "windows"
    pin = json.loads((directory / "process_loopback.json").read_text(encoding="utf-8-sig"))
    assert pin["abi"] == 1 and pin["architecture"] == "x64"
    assert hashlib.sha256((directory / "TranslitoLoopback.dll").read_bytes()).hexdigest() == pin["sha256"]
    assert hashlib.sha256((root / pin["source"]).read_bytes()).hexdigest() == pin["source_sha256"]


def test_gui_refresh_retains_silent_app_instead_of_broadening_to_all_apps(monkeypatch):
    import gui
    from device_utils import InputDeviceChoice
    source = ProcessSource(42, 1, "chrome.exe (PID 42)")
    choice = InputDeviceChoice(source.name, source, True, False)
    class Combo:
        def __init__(self, index=-1):
            self.index, self.text, self.values = index, "", []
        def current(self, index=None):
            if index is None:
                return self.index
            self.index = index
        def __setitem__(self, key, value):
            assert key == "values"
            self.values = value
        def set(self, text):
            self.text = text
    host = gui.TranslatorGUI.__new__(gui.TranslatorGUI)
    host.listen_choices, host.speak_mic_choices, host.output_choices = [choice], [], []
    host.listen_combo, host.speak_mic_combo, host.speak_output_combo = Combo(0), Combo(), Combo()
    host.listen_source_type_var = SimpleNamespace(get=lambda: "App audio")
    host.speak_mic_var = host.speak_output_var = SimpleNamespace(get=lambda: "")
    host.app_audio_hint = SimpleNamespace(configure=Mock())
    host.update_routing_banner = Mock()
    monkeypatch.setattr(gui, "query_input_devices", lambda **kwargs: [])
    monkeypatch.setattr(gui, "query_output_devices", lambda **kwargs: [])
    monkeypatch.setattr("engines.process_audio.supported", lambda: True)
    monkeypatch.setattr("engines.process_audio.active_sources", lambda: [ProcessSource(1, 1, "All apps", exclude=True)])
    for _ in range(2):
        host.refresh_devices()
        assert host.selected_listen_choice().raw is source
        assert host.selected_listen_choice().name.count("not playing") == 1
