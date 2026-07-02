import base64
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

    @property
    def is_playing(self):
        return self._playing.is_set()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._playing.clear()

    def enqueue(self, text, language, voice="Automatic"):
        if not self._running:
            self.start()
        self._queue.put((text, language, voice))

    def _worker(self):
        while self._running:
            item = self._queue.get()
            if item is None:
                continue
            text, language, voice = item
            try:
                self._emit("status", "speaking")
                self._playing.set()
                samples, sample_rate = self.synthesizer.synthesize(text, language, voice)
                if samples.size:
                    self._play(samples, sample_rate)
            except Exception as exc:
                self._emit("error", f"Speech output failed: {exc}")
            finally:
                self._playing.clear()

    def _play(self, samples, sample_rate):
        import sounddevice as sd

        targets = [self.output_device_name]
        if self.monitor and self.output_device_name:
            targets.append("")

        streams = []
        try:
            for target in targets:
                stream, rate = self._open_stream(sd, target)
                streams.append((stream, rate, target))
            translated_streams = []
            for stream, rate, target in streams:
                if rate != sample_rate:
                    translated = resample_audio(samples, sample_rate, rate)
                else:
                    translated = samples.astype(np.float32, copy=False)
                translated_streams.append((stream, translated, target))
            frame = 0
            max_len = max(len(translated) for _stream, translated, _target in translated_streams)
            block = 2048
            while frame < max_len and self._running:
                for stream, translated, target in translated_streams:
                    data = translated[frame : frame + block]
                    if data.size == 0:
                        continue
                    try:
                        stream.write(data)
                    except Exception:
                        self._retry_write(sd, target, data)
                frame += block
        finally:
            for stream, _rate, _target in streams:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _open_stream(self, sd, output_device_name):
        from device_utils import resolve_output_device_index

        device = resolve_output_device_index(output_device_name) if output_device_name else None
        info = sd.query_devices(device, "output")
        rate = int(float(info.get("default_samplerate", 48000)))
        stream = sd.OutputStream(device=device, samplerate=rate, channels=1, dtype="float32")
        stream.start()
        return stream, rate

    def _retry_write(self, sd, output_device_name, data):
        stream = None
        try:
            stream, _rate = self._open_stream(sd, output_device_name)
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
