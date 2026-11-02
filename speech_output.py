import base64
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import wave

import numpy as np


def resample_audio(audio_array, original_sample_rate, target_sample_rate):
    original_sample_rate = int(original_sample_rate)
    target_sample_rate = int(target_sample_rate)
    audio = np.asarray(audio_array, dtype=np.float32)
    if original_sample_rate == target_sample_rate:
        return audio.astype(np.float32, copy=False)
    if audio.size == 0:
        return np.asarray([], dtype=np.float32)
    duration_s = float(audio.shape[0]) / float(original_sample_rate)
    target_len = int(round(duration_s * float(target_sample_rate)))
    if target_len <= 1:
        return np.asarray([], dtype=np.float32)
    original_positions = np.arange(audio.shape[0], dtype=np.float64)
    target_positions = np.linspace(0, audio.shape[0] - 1, num=target_len, dtype=np.float64)
    return np.interp(target_positions, original_positions, audio).astype(np.float32)


class SpeechSynthesizer:
    def synthesize(self, text, language, voice="Automatic"):
        raise NotImplementedError


class LocalSpeechSynthesizer(SpeechSynthesizer):
    def __init__(self, tts_dir="tts_models"):
        self.tts_dir = Path(tts_dir)

    def synthesize(self, text, language, voice="Automatic"):
        text = (text or "").strip()
        if not text:
            return np.asarray([], dtype=np.float32), 16000

        piper_voice = self._select_piper_voice(language, voice)
        if piper_voice is not None and shutil.which("piper"):
            try:
                return self._synthesize_with_piper(text, piper_voice)
            except Exception:
                pass

        try:
            return self._synthesize_with_pyttsx3(text, voice)
        except Exception:
            if os.name == "nt":
                return self._synthesize_with_windows_sapi(text, language, voice)
            raise

    def available_voices(self, language):
        voices = ["Automatic"]
        for voice_path in self._piper_voice_paths(language):
            voices.append(f"piper:{voice_path.stem}")
        try:
            import pyttsx3

            engine = pyttsx3.init()
            for voice in engine.getProperty("voices"):
                name = getattr(voice, "name", "") or getattr(voice, "id", "")
                if name and name not in voices:
                    voices.append(name)
            engine.stop()
        except Exception:
            pass
        return voices

    def _select_piper_voice(self, language, voice):
        if voice and voice != "Automatic" and voice.startswith("piper:"):
            wanted = voice.split(":", 1)[1]
            for voice_path in self.tts_dir.rglob("*.onnx"):
                if voice_path.stem == wanted:
                    return voice_path
        paths = self._piper_voice_paths(language)
        return paths[0] if paths else None

    def _piper_voice_paths(self, language):
        if not self.tts_dir.exists():
            return []
        lowered_language = (language or "").lower()
        paths = sorted(self.tts_dir.rglob("*.onnx"))
        if not lowered_language:
            return paths
        matching = [
            path
            for path in paths
            if lowered_language in str(path).lower().replace("_", "-")
        ]
        return matching or paths

    def _synthesize_with_piper(self, text, voice_path):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "speech.wav"
            command = [
                "piper",
                "--model",
                str(voice_path),
                "--output_file",
                str(out_path),
            ]
            subprocess.run(
                command,
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return read_wav_mono_float32(out_path)

    def _synthesize_with_pyttsx3(self, text, voice):
        import pyttsx3

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "speech.wav"
            engine = pyttsx3.init()
            if voice and voice != "Automatic":
                for candidate in engine.getProperty("voices"):
                    if voice in {getattr(candidate, "name", ""), getattr(candidate, "id", "")}:
                        engine.setProperty("voice", candidate.id)
                        break
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
            engine.stop()
            return read_wav_mono_float32(out_path)

    def _synthesize_with_windows_sapi(self, text, language, voice):
        culture = _culture_for_language(language)
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = str(Path(tmpdir) / "speech.wav")
            safe_path = out_path.replace("'", "''")
            safe_voice = (voice or "").replace("'", "''")
            script = f"""
$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_text}'))
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
  if ('{safe_voice}' -and '{safe_voice}' -ne 'Automatic') {{
    try {{ $s.SelectVoice('{safe_voice}') }} catch {{ }}
  }}
  try {{
    $culture = [Globalization.CultureInfo]::GetCultureInfo('{culture}')
    $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, [System.Speech.Synthesis.VoiceAge]::NotSet, 0, $culture)
  }} catch {{ }}
  $s.SetOutputToWaveFile('{safe_path}')
  $s.Speak($text)
}} finally {{
  $s.Dispose()
}}
"""
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return read_wav_mono_float32(out_path)


@dataclass(frozen=True)
class BufferedVoice:
    samples: np.ndarray
    sample_rate: int


@dataclass(frozen=True)
class StreamVoice(BufferedVoice):
    epoch: int
    stopped: threading.Event


@dataclass(frozen=True)
class _StreamBoundary:
    epoch: int


@dataclass
class _SpeechSession:
    items: queue.Queue = field(default_factory=queue.Queue)
    stopped: threading.Event = field(default_factory=threading.Event)
    playing: threading.Event = field(default_factory=threading.Event)
    stream_stopped: threading.Event = field(default_factory=threading.Event)
    stream_epoch: int = 0
    routes: object = None


# pyttsx3/SAPI may share process-wide engine state across player instances.
# A new transcriber can be created while the old worker finishes synthesis.
_SYNTHESIS_LOCK = threading.Lock()


class SpeechOutputPlayer:
    def __init__(self, output_device_name="", monitor=False, synthesizer=None, on_event=None):
        self.output_device_name = output_device_name or ""
        self.monitor = bool(monitor)
        self.synthesizer = synthesizer or LocalSpeechSynthesizer()
        self.on_event = on_event
        self._queue = queue.Queue()
        self._running = False
        self._thread = None
        self._playing = threading.Event()
        self._session = None
        self._lifecycle_lock = threading.RLock()
        self._synthesis_lock = _SYNTHESIS_LOCK

    @property
    def is_playing(self):
        return self._playing.is_set()

    def start(self):
        with self._lifecycle_lock:
            if self._running:
                return
            session = _SpeechSession()
            self._session = session
            self._queue = session.items
            self._playing = session.playing
            self._running = True
            self._thread = threading.Thread(target=self._worker, args=(session,), daemon=True)
            self._thread.start()

    def stop(self, join_timeout=2):
        with self._lifecycle_lock:
            self._running = False
            session, worker = self._session, self._thread
            if session:
                session.stopped.set()
                session.stream_stopped.set()
                session.playing.clear()
                if session.routes:
                    session.routes.abort()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            self._queue.put(None)
            self._playing.clear()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=join_timeout)
        with self._lifecycle_lock:
            if self._thread is worker:
                self._thread = None

    def enqueue(self, text, language, voice="Automatic"):
        with self._lifecycle_lock:
            if not self._running:
                self.start()
            self._queue.put((text, language, voice))

    def enqueue_audio(self, samples, sample_rate):
        """Queue one completed mic utterance; never open a live mic/output loop."""
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim != 1 or int(sample_rate) <= 0 or not np.isfinite(audio).all():
            raise ValueError("Pass-through requires finite mono audio and a valid sample rate")
        if not audio.size:
            return
        with self._lifecycle_lock:
            if not self._running:
                self.start()
            self._queue.put(BufferedVoice(audio.copy(), int(sample_rate)))

    def _active(self, session):
        return self._running and self._session is session and not session.stopped.is_set()

    def play_stream(self, pcm_bytes, rate=24000):
        """Queue PCM16 chunks into persistent output streams; never invoke TTS."""
        if len(pcm_bytes) % 2 or int(rate) <= 0:
            raise ValueError("Streaming output requires whole PCM16 samples and a valid rate")
        if not pcm_bytes:
            return False
        audio = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32) / 32768
        with self._lifecycle_lock:
            if not self._running:
                return False
            self._queue.put(StreamVoice(audio, int(rate), self._session.stream_epoch, self._session.stream_stopped))
            return True

    def reset_stream(self):
        """Discard queued/in-flight old stream audio after reconnect or Stop."""
        with self._lifecycle_lock:
            session = self._session
            if session is None:
                return
            previous = session.stream_stopped
            previous.set()
            session.stream_stopped = threading.Event()
            session.stream_epoch += 1
            if session.routes and session.routes.stop_event is previous:
                session.routes.abort()
            session.items.put(_StreamBoundary(session.stream_epoch))

    def _worker(self, session=None):
        if session is None:
            session = self._session or _SpeechSession(items=self._queue, playing=self._playing)
            self._session = session
        stream_epoch = None
        try:
            while self._active(session):
                item = session.items.get()
                if item is None:
                    continue
                if not self._active(session):
                    break
                try:
                    if isinstance(item, _StreamBoundary):
                        if session.routes:
                            session.routes.close()
                            session.routes = None
                        stream_epoch = None
                        continue
                    self._emit("status", "speaking")
                    session.playing.set()
                    if isinstance(item, StreamVoice):
                        if item.epoch != session.stream_epoch:
                            continue
                        if stream_epoch != item.epoch or session.routes is None:
                            if session.routes:
                                session.routes.close()
                            session.routes = _PlaybackRoutes(self, item.stopped)
                            stream_epoch = item.epoch
                        session.routes.write(item.samples, item.sample_rate)
                        continue
                    if session.routes:
                        session.routes.close()
                        session.routes = None
                        stream_epoch = None
                    if isinstance(item, BufferedVoice):
                        samples, sample_rate = item.samples, item.sample_rate
                    else:
                        text, language, voice = item
                        with self._synthesis_lock:
                            if not self._active(session):
                                continue
                            samples, sample_rate = self.synthesizer.synthesize(text, language, voice)
                    if samples.size and self._active(session):
                        self._play(samples, sample_rate, stop_event=session.stopped)
                except Exception as exc:
                    if session.routes:
                        session.routes.close()
                        session.routes = None
                    if self._active(session):
                        self._emit("error", f"Speech output failed: {exc}")
                finally:
                    session.playing.clear()
                    if self._active(session) and session.items.empty():
                        self._emit("status", "listening")
        finally:
            if session.routes:
                session.routes.close()
                session.routes = None

    def _play(self, samples, sample_rate, stop_event=None):
        routes = _PlaybackRoutes(self, stop_event)
        with self._lifecycle_lock:
            session = self._session
            if session and session.stopped is stop_event:
                session.routes = routes
        try:
            routes.write(samples, sample_rate)
            routes.flush()
        finally:
            routes.close()
            if session and session.routes is routes:
                session.routes = None

    def _open_stream(self, sd, output_device_name):
        from device_utils import resolve_output_device_index

        device = resolve_output_device_index(output_device_name) if output_device_name else None
        info = sd.query_devices(device, "output")
        rate = int(float(info.get("default_samplerate", 48000)))
        stream = sd.OutputStream(device=device, samplerate=rate, channels=1, dtype="float32")
        stream.start()
        return stream, rate

    def _retry_write(self, sd, output_device_name, data, sample_rate=None, stop_event=None):
        stream = None
        try:
            if stop_event is not None and stop_event.is_set():
                return
            stream, rate = self._open_stream(sd, output_device_name)
            if sample_rate is not None and rate != sample_rate:
                data = resample_audio(data, sample_rate, rate)
            if stop_event is None or not stop_event.is_set():
                stream.write(data)
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _emit(self, event_type, payload):
        if callable(self.on_event):
            try:
                self.on_event(event_type, payload)
            except Exception:
                pass


class _StreamResampler:
    """Linear interpolation with a retained boundary and no per-chunk drift."""
    def __init__(self, source_rate, target_rate):
        self.source_rate, self.target_rate = source_rate, target_rate
        self.input_count = self.output_count = 0
        self.last = None

    def push(self, samples):
        if not samples.size:
            return samples
        offset = self.input_count - int(self.last is not None)
        values = np.concatenate(([self.last], samples)) if self.last is not None else samples
        self.input_count += len(samples)
        end = math.floor((self.input_count - 1) * self.target_rate / self.source_rate) + 1
        positions = np.arange(self.output_count, end, dtype=np.float64) * self.source_rate / self.target_rate - offset
        output = np.interp(positions, np.arange(len(values)), values).astype(np.float32)
        self.output_count = end
        self.last = float(samples[-1])
        return output

    def flush(self):
        end = round(self.input_count * self.target_rate / self.source_rate)
        output = np.full(max(0, end - self.output_count), self.last or 0, dtype=np.float32)
        self.output_count = end
        return output


@dataclass
class _OutputRoute:
    target: str
    stream: object
    rate: int
    resampler: object = None


class _PlaybackRoutes:
    def __init__(self, player, stop_event=None):
        self.player, self.stop_event = player, stop_event
        self.routes = []

    def active(self):
        return self.player._running and not (self.stop_event and self.stop_event.is_set())

    def _open(self):
        import sounddevice as sd
        targets = [self.player.output_device_name]
        if self.player.monitor and targets[0]:
            targets.append("")
        for target in targets:
            if not self.active():
                return
            stream, rate = self.player._open_stream(sd, target)
            self.routes.append(_OutputRoute(target, stream, rate))
            if not self.active():
                self.abort()

    def write(self, samples, rate):
        if not self.active():
            return
        if not self.routes:
            self._open()
        # Every route consumes the same time interval, even at 44.1/48 kHz.
        block = max(1, round(rate * .02))
        for offset in range(0, len(samples), block):
            if not self.active():
                return
            for route in self.routes:
                if not route.resampler or route.resampler.source_rate != rate:
                    if route.resampler:
                        self._write(route, route.resampler.flush())
                    route.resampler = _StreamResampler(rate, route.rate)
                self._write(route, route.resampler.push(samples[offset:offset + block]))

    def _write(self, route, data):
        if not data.size or not self.active():
            return
        try:
            route.stream.write(data)
        except Exception:
            if not self.active():
                return
            import sounddevice as sd
            from device_utils import refresh_portaudio_devices
            old_rate = route.rate
            # PortAudio enumerates hot-plugged endpoints only after a reset.
            # A reset invalidates every stream in this player, including its
            # monitor, so close all routes before refreshing and reopening.
            for candidate in self.routes:
                self._close_stream(candidate.stream)
            if not self.active():
                return
            refresh_portaudio_devices()
            for candidate in self.routes:
                if not self.active():
                    return
                previous_rate = candidate.rate
                candidate.stream, candidate.rate = self.player._open_stream(sd, candidate.target)
                if candidate.rate != previous_rate:
                    candidate.resampler = None
            if route.rate != old_rate:
                data = resample_audio(data, old_rate, route.rate)
            if self.active():
                route.stream.write(data)

    def flush(self):
        for route in self.routes:
            if route.resampler:
                self._write(route, route.resampler.flush())

    def abort(self):
        for route in tuple(self.routes):
            try:
                route.stream.abort()
            except Exception:
                pass

    @staticmethod
    def _close_stream(stream):
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def close(self):
        for route in self.routes:
            self._close_stream(route.stream)
        self.routes.clear()


def read_wav_mono_float32(path):
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio.astype(np.float32, copy=False), sample_rate


def _culture_for_language(language):
    mapping = {
        "ar": "ar-SA",
        "en": "en-US",
        "fr": "fr-FR",
        "es": "es-ES",
        "de": "de-DE",
        "it": "it-IT",
        "pt": "pt-PT",
        "ru": "ru-RU",
        "tr": "tr-TR",
        "fa": "fa-IR",
        "ur": "ur-PK",
    }
    language = (language or "en").split("-")[0].lower()
    return mapping.get(language, "en-US")
