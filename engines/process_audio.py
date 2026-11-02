"""In-memory WASAPI process-tree capture. No original-audio files or uploads."""
from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

import numpy as np


class ProcessAudioError(RuntimeError):
    pass


def supported():
    return sys.platform == "win32" and sys.maxsize > 2**32 and sys.getwindowsversion().build >= 20348


class NativeBridge:
    def __init__(self):
        if not supported():
            raise ProcessAudioError("App audio needs 64-bit Windows build 20348 or later (including Windows 11). Use Device on older Windows.")
        directory = Path(__file__).parent / "data" / "windows"
        pin = json.loads((directory / "process_loopback.json").read_text(encoding="utf-8"))
        path = directory / "TranslitoLoopback.dll"
        if hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
            raise ProcessAudioError("App-audio component verification failed. Reinstall Translito from its official release.")
        self.dll = ctypes.WinDLL(str(path))
        self.dll.translito_capture_abi.restype = ctypes.c_uint
        if self.dll.translito_capture_abi() != 1:
            raise ProcessAudioError("The app-audio component has an incompatible version.")
        self.callback_type = ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_short), ctypes.c_uint, ctypes.c_void_p)
        self.dll.translito_capture_run.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_void_p, self.callback_type, ctypes.c_void_p]
        self.dll.translito_capture_run.restype = ctypes.c_long
        self.dll.translito_capture_processes.argtypes = [ctypes.POINTER(ctypes.c_ulong), ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
        self.dll.translito_capture_processes.restype = ctypes.c_long
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.CreateEventW.restype = ctypes.c_void_p
        self.kernel.SetEvent.argtypes = [ctypes.c_void_p]
        self.kernel.SetEvent.restype = ctypes.c_int
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.restype = ctypes.c_int

    def pids(self):
        values, count = (ctypes.c_ulong * 256)(), ctypes.c_uint()
        result = self.dll.translito_capture_processes(values, 256, ctypes.byref(count))
        if result < 0:
            raise ProcessAudioError("Audio apps could not be listed. Refresh or use a Device source.")
        return list(values[:count.value])

    def create_stop(self):
        handle = self.kernel.CreateEventW(None, True, False, None)
        if not handle:
            raise ProcessAudioError("App-audio capture could not create its stop event.")
        return handle

    def run(self, source, stop, callback):
        # Keep the native callback alive for the entire blocking call.
        native_callback = self.callback_type(callback)
        return self.dll.translito_capture_run(source.pid, source.exclude, stop, native_callback, None)

    def stop(self, handle):
        self.kernel.SetEvent(handle)

    def close(self, handle):
        self.kernel.CloseHandle(handle)


@dataclass(frozen=True)
class ProcessSource:
    is_process_loopback = True
    pid: int
    birth: float
    name: str
    exclude: bool = False
    isloopback: bool = True

    def validate(self, process_factory=None):
        if process_factory is None:
            import psutil
            process_factory = psutil.Process
        try:
            if process_factory(self.pid).create_time() != self.birth:
                raise ValueError("PID was reused")
        except Exception:
            raise ProcessAudioError("That audio app has closed or restarted. Refresh and select it again.") from None

    def recorder(self, samplerate=48000, *, bridge=None):
        if int(samplerate) != 48000:
            raise ProcessAudioError("App audio captures at 48000 Hz; choose the default capture sample rate.")
        self.validate()
        return ProcessRecorder(self, bridge or NativeBridge())


def active_sources(*, bridge=None, process_factory=None, own_pid=None):
    if process_factory is None:
        import psutil
        process_factory = psutil.Process
    own_pid = os.getpid() if own_pid is None else own_pid
    own = process_factory(own_pid)
    result = [ProcessSource(own_pid, own.create_time(), "All apps (exclude Translito)", exclude=True)]
    seen = set()
    for pid in (bridge or NativeBridge()).pids():
        try:
            process = process_factory(pid)
            parents = process.parents()
            if pid == own_pid or own_pid in {parent.pid for parent in parents}:
                continue
            # Browser audio normally belongs to a utility child. Select its
            # same-executable application root to include sibling renderers.
            for parent in parents:
                if parent.name().casefold() != process.name().casefold():
                    break
                process = parent
            if process.pid in seen:
                continue
            seen.add(process.pid)
            result.append(ProcessSource(process.pid, process.create_time(), f"{process.name()} (PID {process.pid})"))
        except Exception:
            continue  # A process can exit between session enumeration and lookup.
    return result[:1] + sorted(result[1:], key=lambda item: item.name.casefold())


class ProcessRecorder:
    def __init__(self, source, bridge):
        self.source, self.bridge = source, bridge
        self.blocks = queue.Queue()
        self.pending = np.empty((0, 2), dtype=np.float32)
        self.ready, self.ended, self.stopped = threading.Event(), threading.Event(), threading.Event()
        self.error = None
        self.handle = None

    def __enter__(self):
        self.handle = self.bridge.create_stop()
        def received(pointer, frames, _context):
            if frames == 0:
                self.ready.set()
            elif not self.stopped.is_set():
                samples = (np.ctypeslib.as_array(pointer, shape=(frames * 2,)).astype(np.float32) / 32768
                           if pointer else np.zeros(frames * 2, dtype=np.float32))
                self.blocks.put(samples.reshape(-1, 2))
        def run():
            try:
                if self.bridge.run(self.source, self.handle, received) < 0:
                    self.error = ProcessAudioError("App-audio capture failed. The app may have closed; refresh the source or use Device.")
            except Exception:
                self.error = ProcessAudioError("App-audio capture could not start. Use Device or try again.")
            finally:
                self.ended.set()
                self.ready.set()
        self.worker = threading.Thread(target=run, daemon=True, name="Translito process audio")
        self.worker.start()
        if not self.ready.wait(6) or self.error or self.ended.is_set():
            self.__exit__(None, None, None)
            raise self.error or ProcessAudioError("App-audio capture did not start in time.")
        return self

    def record(self, numframes):
        if self.error:
            raise self.error
        frames = int(numframes)
        if frames <= 0:
            raise ValueError("numframes must be positive")
        # Process loopback may emit no packets while the app is silent. Return
        # bounded silence so the desktop's existing Stop loop stays responsive.
        deadline = time.monotonic() + max(.1, frames / 48000 + .05)
        pieces, count = [], 0
        if len(self.pending):
            pieces.append(self.pending)
            count = len(self.pending)
        while count < frames and not self.stopped.is_set():
            if self.error:
                raise self.error
            if self.ended.is_set():
                raise ProcessAudioError("App-audio capture stopped. Refresh the audio source and start again.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                block = self.blocks.get(timeout=min(.1, remaining))
                pieces.append(block)
                count += len(block)
            except queue.Empty:
                pass
        if count < frames:
            pieces.append(np.zeros((frames - count, 2), np.float32))
        audio = np.concatenate(pieces, axis=0)
        self.pending = audio[frames:]
        return audio[:frames]

    def __exit__(self, *_args):
        self.stopped.set()
        if self.handle:
            self.bridge.stop(self.handle)
        self.worker.join(timeout=3)
        if not self.worker.is_alive():
            self.bridge.close(self.handle)
            self.handle = None
        # The worker retains its callback/handle if a Windows call is stuck;
        # do not free objects still used by native code. No audio is retained.
        self.pending = np.empty((0, 2), dtype=np.float32)
        while True:
            try:
                self.blocks.get_nowait()
            except queue.Empty:
                break
