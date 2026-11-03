"""Pinned optional VB-CABLE installation and a local tone loopback self-test."""
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import threading
import time
import zipfile

import numpy as np

from windows_audio import audio_com_context


PACKAGE = json.loads((Path(__file__).parent / "data" / "vbcable.json").read_text(encoding="utf-8"))


class VirtualMicError(RuntimeError):
    pass


@dataclass(frozen=True)
class CableTestResult:
    passed: bool
    band_dbfs: float
    message: str


def bundle_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "redist" / "vbcable"
    return Path(__file__).resolve().parents[1] / "installer" / "redist" / "vbcable"


def verified_archive(path=None):
    path = Path(path) if path else bundle_directory() / PACKAGE["filename"]
    try:
        data = path.read_bytes()
    except OSError:
        raise VirtualMicError("The bundled VB-CABLE package is missing. Reinstall Translito from its official installer.") from None
    if len(data) != PACKAGE["size"] or hashlib.sha256(data).hexdigest() != PACKAGE["sha256"]:
        raise VirtualMicError("VB-CABLE package verification failed. No driver was extracted or started.")
    return data


def restart_windows(*, consent=False, launcher=None):
    """Only an explicit Restart-button confirmation can request a reboot."""
    if consent is not True:
        raise VirtualMicError("Restart requires explicit consent.")
    if launcher is None:
        import subprocess
        launcher = subprocess.Popen
    return launcher(["shutdown.exe", "/r", "/t", "0"])


def prepare_installer(path=None, *, cache_root=None):
    data = verified_archive(path)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        # Check every path before creating an extraction directory. The source
        # is pinned too; these checks also make future package updates safer.
        for member in members:
            item = PurePosixPath(member.filename.replace("\\", "/"))
            if (item.is_absolute() or ".." in item.parts or ":" in member.filename
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise VirtualMicError("The VB-CABLE archive contains an invalid path.")
        if sum(member.file_size for member in members) > 16 * 1024 * 1024:
            raise VirtualMicError("The VB-CABLE archive is larger than its verified package policy.")
        executable = archive.read(PACKAGE["setup"])
        if hashlib.sha256(executable).hexdigest() != PACKAGE["setup_sha256"]:
            raise VirtualMicError("VB-CABLE setup verification failed.")
        if cache_root is None:
            from app_config import CONFIG_FILE
            cache_root = CONFIG_FILE.parent / "drivers"
        root = Path(cache_root)
        root.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix="vbcable-", dir=root))
        archive.extractall(destination)
    return destination / PACKAGE["setup"]


def _elevate(executable, arguments):
    if os.name != "nt":
        raise VirtualMicError("The VB-CABLE Windows installer requires Windows.")
    import ctypes
    from ctypes import wintypes
    shell = ctypes.windll.shell32.ShellExecuteW
    shell.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
    shell.restype = ctypes.c_ssize_t
    # Only this verified vendor child is elevated; Translito stays unprivileged.
    result = shell(None, "runas", str(executable), arguments, str(executable.parent), 1)
    if result <= 32:
        raise VirtualMicError("Windows cancelled or could not start the VB-CABLE installer. The driver was not installed by Translito.")


def install_virtual_mic(*, consent=False, path=None, cache_root=None, launcher=None):
    if consent is not True:
        raise VirtualMicError("Explicit consent is required before installing VB-CABLE.")
    executable = prepare_installer(path, cache_root=cache_root)
    (launcher or _elevate)(executable, "-i -h")
    return executable


def cable_output(choices):
    return next((choice for choice in choices if "cable input" in choice.name.casefold()), None)


def wait_for_cable(*, query=None, stop_event=None, timeout=120, interval=2, on_poll=None):
    if query is None:
        from device_utils import query_output_devices
        query = lambda: query_output_devices(refresh=True)
    stopped = stop_event or threading.Event()
    deadline = time.monotonic() + timeout
    while not stopped.is_set():
        found = cable_output(query())
        if found:
            return found
        if on_poll:
            on_poll()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        stopped.wait(min(interval, remaining))
    return None


def test_tone(sample_rate=48000):
    count = round(.8 * sample_rate)
    phase = np.arange(count, dtype=np.float64) / sample_rate
    tone = (10 ** (-12 / 20) * np.sin(2 * np.pi * 1000 * phase)).astype(np.float32)
    ramp = max(1, round(sample_rate * .01))
    tone[:ramp] *= np.linspace(0, 1, ramp)
    tone[-ramp:] *= np.linspace(1, 0, ramp)
    return tone


def tone_band_dbfs(samples, sample_rate):
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.ndim != 2 or not audio.size or not np.isfinite(audio).all() or sample_rate <= 2100:
        return -math.inf
    spectrum = np.fft.rfft(audio, axis=0)
    frequencies = np.fft.rfftfreq(len(audio), 1 / sample_rate)
    band = (frequencies >= 950) & (frequencies <= 1050)
    # Use the strongest channel: averaging a multichannel cable can attenuate
    # valid stereo or cancel phase-inverted channels.
    rms = np.sqrt(2 * np.sum(np.abs(spectrum[band]) ** 2, axis=0)) / len(audio)
    maximum = float(np.max(rms))
    return 20 * math.log10(maximum) if maximum > 0 else -math.inf


def self_test(output, *, sounddevice=None, soundcard=None):
    if output is None or "cable input" not in output.name.casefold():
        return CableTestResult(False, -math.inf, "Select CABLE Input first. Install the virtual microphone if it is missing.")
    try:
        # SoundCard also initializes COM at first import; load it before adding
        # our thread's reference (its import rejects CoInitializeEx's S_FALSE).
        if sounddevice is None:
            import sounddevice
        if soundcard is None:
            import soundcard
        with audio_com_context():
            return _self_test(output, sounddevice=sounddevice, soundcard=soundcard)
    except Exception:
        return CableTestResult(False, -math.inf, "Virtual-mic test could not run. Check CABLE Input/Output in Windows Sound settings.")


def _self_test(output, *, sounddevice=None, soundcard=None):
    try:
        devices = soundcard.all_microphones(include_loopback=False)
    except Exception:
        return CableTestResult(False, -math.inf, "Virtual microphones could not be listed. Check Windows Sound settings and test again.")
    capture = next((device for device in devices if "cable output" in device.name.casefold()), None)
    if capture is None:
        return CableTestResult(False, -math.inf, "CABLE Output was not found. Restart Windows to finish driver installation.")
    ready, finished, cancel = threading.Event(), threading.Event(), threading.Event()
    recorded, errors = [], []
    rate, block = 48000, 4800
    def record():
        try:
            with audio_com_context(), capture.recorder(samplerate=rate, channels=2) as recorder:
                ready.set()
                for _ in range(12):
                    if cancel.is_set():
                        break
                    recorded.append(recorder.record(numframes=block))
        except Exception:
            errors.append(True)
        finally:
            ready.set()
            finished.set()
    worker = threading.Thread(target=record, daemon=True, name="Translito cable self-test")
    worker.start()
    stream = None
    try:
        if not ready.wait(2) or errors:
            raise VirtualMicError("Virtual-mic recording could not start.")
        playback_rate = int(output.default_samplerate)
        stream = sounddevice.OutputStream(device=output.index, samplerate=playback_rate, channels=1, dtype="float32")
        stream.start()
        stream.write(test_tone(playback_rate))
        stream.stop()
        if not finished.wait(3) or errors or not recorded:
            raise VirtualMicError("Virtual-mic recording did not complete.")
        level = tone_band_dbfs(np.concatenate(recorded, axis=0), rate)
        passed = level >= -30
        return CableTestResult(passed, level, "Virtual microphone passed." if passed else
            "The test tone did not reach CABLE Output. Check its mute/level controls in Windows Sound settings.")
    except Exception:
        return CableTestResult(False, -math.inf, "Virtual-mic test could not run. Check CABLE Input/Output in Windows Sound settings.")
    finally:
        cancel.set()
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        worker.join(timeout=.3)
