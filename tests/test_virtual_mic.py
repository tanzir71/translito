import hashlib
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import numpy as np
import pytest

import engines.virtual_mic as cable


def test_bundled_archive_matches_both_pins_and_retains_vendor_files(tmp_path):
    data = cable.verified_archive()
    pin = (Path(__file__).resolve().parents[1] / "installer" / "vbcable.sha256").read_text().split()
    assert pin == [hashlib.sha256(data).hexdigest(), cable.PACKAGE["filename"]]
    script = (Path(__file__).resolve().parents[1] / "installer" / "Translito.iss").read_text()
    assert f"VBCableHash = '{pin[0]}'" in script
    assert f"VBCableSetupHash = '{cable.PACKAGE['setup_sha256']}'" in script
    executable = cable.prepare_installer(cache_root=tmp_path / "drivers")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert executable.read_bytes() == archive.read("VBCABLE_Setup_x64.exe")
        assert (executable.parent / "readme.txt").read_bytes() == archive.read("readme.txt")
        assert sorted(path.name for path in executable.parent.iterdir()) == sorted(archive.namelist())


def test_explicit_consent_and_hash_are_required_before_extract_or_launch(tmp_path):
    launch = Mock()
    with pytest.raises(cable.VirtualMicError, match="consent"):
        cable.install_virtual_mic(cache_root=tmp_path / "drivers", launcher=launch)
    bad = tmp_path / "changed.zip"
    bad.write_bytes(b"not the official package")
    with pytest.raises(cable.VirtualMicError, match="verification failed"):
        cable.install_virtual_mic(consent=True, path=bad, cache_root=tmp_path / "drivers", launcher=launch)
    launch.assert_not_called()
    assert not (tmp_path / "drivers").exists()
    executable = cable.install_virtual_mic(consent=True, cache_root=tmp_path / "drivers", launcher=launch)
    launch.assert_called_once_with(executable, "-i -h")


def test_updated_archive_cannot_escape_extraction_directory(tmp_path, monkeypatch):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../outside.exe", b"not executable")
    data = path.read_bytes()
    monkeypatch.setattr(cable, "PACKAGE", {**cable.PACKAGE, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    with pytest.raises(cable.VirtualMicError, match="invalid path"):
        cable.prepare_installer(path, cache_root=tmp_path / "drivers")
    assert not (tmp_path / "drivers").exists() and not (tmp_path.parent / "outside.exe").exists()


def test_tone_is_08_seconds_minus12_db_peak_and_band_rejects_unrelated_audio():
    tone = cable.test_tone(48000)
    assert len(tone) == 38400 and tone.dtype == np.float32
    assert 20 * np.log10(np.max(np.abs(tone))) == pytest.approx(-12, abs=.01)
    assert cable.tone_band_dbfs(tone, 48000) > -16
    assert cable.tone_band_dbfs(np.zeros(48000, np.float32), 48000) == -np.inf
    wrong = .25 * np.sin(2 * np.pi * 2000 * np.arange(48000) / 48000)
    assert cable.tone_band_dbfs(wrong, 48000) < -30
    # Cable channels can be inverted; summing them would hide a healthy route.
    assert cable.tone_band_dbfs(np.column_stack((tone, -tone)), 48000) > -16


def test_self_test_targets_only_cable_and_records_the_virtual_endpoint():
    played = threading.Event()
    recorded = np.zeros((57600, 2), np.float32)
    tone = cable.test_tone()
    recorded[4800:4800 + len(tone), :] = tone[:, None]
    offset = [0]
    calls = []
    class Recorder:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def record(self, numframes):
            assert played.wait(1)
            start = offset[0]
            offset[0] += numframes
            return recorded[start:offset[0]]
    def recorder(**kwargs):
        assert kwargs == {"samplerate": 48000, "channels": 2}
        return Recorder()
    class Stream:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def start(self):
            pass
        def write(self, data):
            assert len(data) == 38400
            played.set()
        def stop(self):
            pass
        def close(self):
            pass
    sd = SimpleNamespace(OutputStream=Stream)
    sc = SimpleNamespace(all_microphones=lambda **kw: [SimpleNamespace(name="CABLE Output (VB-Audio)", recorder=recorder)])
    output = SimpleNamespace(name="CABLE Input (VB-Audio)", index=42, default_samplerate=48000)
    result = cable.self_test(output, sounddevice=sd, soundcard=sc)
    assert result.passed and result.band_dbfs >= -30
    assert calls[0]["device"] == 42
    missing = cable.self_test(None, sounddevice=sd, soundcard=sc)
    assert not missing.passed and len(calls) == 1
    speakers = cable.self_test(SimpleNamespace(name="Speakers"), sounddevice=sd, soundcard=sc)
    assert not speakers.passed and len(calls) == 1


def test_polling_selects_only_cable_input_and_cancellation_does_not_wait():
    query = Mock(side_effect=[[SimpleNamespace(name="Speakers")], [SimpleNamespace(name="CABLE Input (VB-Audio)")]])
    assert cable.wait_for_cable(query=query, interval=0, timeout=1).name.startswith("CABLE Input")
    stop = threading.Event()
    stop.set()
    query = Mock()
    assert cable.wait_for_cable(query=query, stop_event=stop) is None
    query.assert_not_called()
    assert cable.wait_for_cable(query=lambda **kwargs: [], interval=.001, timeout=.002) is None


def test_restart_never_runs_without_an_explicit_button_confirmation():
    launch = Mock()
    with pytest.raises(cable.VirtualMicError, match="consent"):
        cable.restart_windows(launcher=launch)
    launch.assert_not_called()
    cable.restart_windows(consent=True, launcher=launch)
    launch.assert_called_once_with(["shutdown.exe", "/r", "/t", "0"])


def test_device_lookup_does_not_reset_existing_portaudio_streams(monkeypatch):
    import device_utils
    import sys
    reset = Mock()
    monkeypatch.setattr(device_utils, "refresh_portaudio_devices", reset)
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(query_devices=lambda: [
        {"name": "CABLE Input", "max_output_channels": 2, "default_samplerate": 48000}]))
    assert device_utils.resolve_output_device_index("CABLE Input") == 0
    reset.assert_not_called()
    device_utils.query_output_devices(refresh=True)
    reset.assert_called_once()
