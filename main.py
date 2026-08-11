#!/usr/bin/env python3
"""
Desktop audio transcriber, translator, and Speak Mode runtime for Windows.
"""

import atexit
from datetime import datetime
import os
import queue
import sys
import threading
import time
import warnings

warnings.filterwarnings("ignore")
warnings.filterwarnings(
    "ignore",
    message=r"`return_token_timestamps` is deprecated.*",
    category=FutureWarning,
)

from app_config import (
    load_device_config as load_device_config_from_file,
    load_runtime_config,
    save_device_config as save_device_config_to_file,
    save_runtime_config,
)
from audio_processing import (
    AudioChunkProcessor,
    AudioChunkResult,
    DROP_DIGITAL_SILENCE,
    resample_audio,
)
from device_utils import should_apply_mic_noise_gate
from model_loading import GLOBAL_MODEL_MANAGER
from speech_output import SpeechOutputPlayer


CONFIG_FILE = "config.ini"

missing_packages = []
dependency_errors = {}


def record_dependency_error(package_name, error):
    if package_name not in missing_packages:
        missing_packages.append(package_name)
    dependency_errors[package_name] = error


try:
    import keyboard
except Exception as exc:
    keyboard = None
    record_dependency_error("keyboard", exc)
try:
    import torch
except Exception as exc:
    torch = None
    record_dependency_error("torch", exc)
try:
    import soundcard as sc
except Exception as exc:
    sc = None
    record_dependency_error("soundcard", exc)
else:
    warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)
try:
    import numpy as np
except Exception as exc:
    np = None
    record_dependency_error("numpy", exc)
try:
    from transformers import pipeline as _transformers_pipeline  # noqa: F401
except Exception as exc:
    record_dependency_error("transformers", exc)


def dependency_failure_message():
    if not missing_packages:
        return None

    lines = ["Missing or incompatible required Python packages:"]
    for package_name in missing_packages:
        lines.append(f"  - {package_name}")
        error = dependency_errors.get(package_name)
        if error:
            lines.append(f"    {error}")

    lines.append("")
    lines.append("Install or repair dependencies:")
    transformers_error = str(dependency_errors.get("transformers", ""))
    if "huggingface-hub" in transformers_error:
        lines.append('  pip install "huggingface-hub>=0.34.0,<1.0"')
    else:
        lines.append("  pip install -r requirements.txt")

    lines.append("")
    lines.append("If torch installs as CPU-only and you want GPU (CUDA):")
    lines.append("  pip uninstall -y torch torchvision torchaudio")
    lines.append(
        "  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128"
    )
    return "\n".join(lines)


def require_dependencies():
    failure_message = dependency_failure_message()
    if failure_message:
        print("\n" + failure_message)
        sys.exit(1)

    extra_missing = []
    try:
        import sentencepiece  # noqa: F401
    except Exception:
        extra_missing.append("sentencepiece")
    try:
        import google.protobuf  # noqa: F401
    except Exception:
        extra_missing.append("protobuf")

    if extra_missing:
        print("\nMissing optional-but-recommended packages (used by transformer models/tokenizers):")
        for package_name in extra_missing:
            print(f"  - {package_name}")
        print("\nInstall:")
        print(f"  pip install {' '.join(extra_missing)}")


def load_device_config():
    return load_device_config_from_file(CONFIG_FILE)


def save_device_config(device_name):
    save_device_config_to_file(device_name, CONFIG_FILE)
    print(f"Device '{device_name}' saved as default.")


def find_device_by_name(device_name):
    if not sc:
        return None
    for device in sc.all_microphones(include_loopback=True):
        if device.name == device_name:
            return device
    return None


def translation_target_from_model(model_name, fallback="en"):
    tail = (model_name or "").rsplit("/", 1)[-1]
    parts = tail.split("-")
    return (parts[-1] if len(parts) >= 2 else fallback).strip().lower() or fallback


class ArabicAudioTranscriber:
    def __init__(
        self,
        selected_device=None,
        on_event=None,
        interactive=True,
        asr_language=None,
        translation_model=None,
        mode="listen",
        target_language=None,
        speech_output_device_name="",
        speech_voice="Automatic",
        monitor_spoken_audio=False,
        mic_noise_gate=None,
        chunk_duration=None,
        transcript_folder=None,
    ):
        print("\nInitializing Translito...")

        self.selected_device = selected_device
        self.on_event = on_event
        self.interactive = interactive
        self.mode = mode if mode in {"listen", "speak"} else "listen"
        self.device_change_requested = False

        self.offline_only = os.environ.get("OFFLINE_ONLY", "0").strip() == "1"
        self.asr_language = (asr_language or os.environ.get("ASR_LANGUAGE", "ar-AR")).strip() or "ar-AR"
        self.whisper_language = self.asr_language.split("-")[0].strip().lower() or "ar"
        self.audio_debug = os.environ.get("AUDIO_DEBUG", "0").strip() == "1"
        self.translation_model_name = (
            translation_model or os.environ.get("TRANSLATION_MODEL", "Helsinki-NLP/opus-mt-ar-en")
        ).strip()
        self.translation_target_language = (
            (target_language or translation_target_from_model(self.translation_model_name)).split("-")[0].lower()
        )
        self.speech_output_device_name = speech_output_device_name or ""
        self.speech_voice = speech_voice or "Automatic"
        self.monitor_spoken_audio = bool(monitor_spoken_audio)
        runtime_config = load_runtime_config(CONFIG_FILE)
        self.mic_noise_gate = (
            runtime_config.mic_noise_gate
            if mic_noise_gate is None
            else max(0.0, float(mic_noise_gate))
        )

        try:
            capture_sr_env = int(os.environ.get("CAPTURE_SAMPLE_RATE", "0").strip() or "0")
        except Exception:
            capture_sr_env = 0
        if capture_sr_env > 0:
            self.capture_sample_rate = capture_sr_env
        else:
            is_loopback = bool(getattr(self.selected_device, "isloopback", False))
            self.capture_sample_rate = 48000 if is_loopback else 16000

        self.sample_rate = 16000
        if chunk_duration is not None:
            self.chunk_duration = min(15.0, max(3.0, float(chunk_duration)))
        else:
            try:
                self.chunk_duration = float(
                    os.environ.get("CHUNK_DURATION", str(runtime_config.chunk_duration)).strip()
                )
            except Exception:
                self.chunk_duration = runtime_config.chunk_duration
        self.transcript_folder = transcript_folder or "transcripts"
        self.last_saved_path = None

        self.transcripts = []
        self.session_start_time = datetime.now()
        self.audio_queue = queue.Queue()
        self.running = False
        self._silence_run = 0
        self._last_audio_hint_time = 0.0
        self._debug_counter = 0
        self._capture_thread = None
        self._process_thread = None
        self.speech_player = None

        atexit.register(self.save_transcript)

        self.torch_device = 0 if (torch and torch.cuda.is_available()) else -1
        self.torch_dtype = torch.float16 if self.torch_device == 0 else None
        if self.torch_device == 0:
            print("GPU detected (CUDA). Using GPU acceleration.")
        else:
            print("CUDA not available. Using CPU.")

        self.asr = None
        self.translator = None
        self.whisper_model = os.environ.get("WHISPER_MODEL", "openai/whisper-small").strip()
        if self.offline_only:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        try:
            loaded_models = GLOBAL_MODEL_MANAGER.load_models(
                whisper_model=self.whisper_model,
                translation_model=self.translation_model_name,
                torch_device=self.torch_device,
                torch_dtype=self.torch_dtype,
                offline_only=self.offline_only,
                on_event=self.emit,
            )
            self.asr = loaded_models.asr
            self.translator = loaded_models.translator
            print("Offline models ready.")
        except Exception as exc:
            if self.offline_only:
                print("Offline-only is enabled. Set OFFLINE_ONLY=0 once to allow model downloads.")
            raise RuntimeError(f"Failed to initialize offline models: {exc}") from exc

        if self.mode == "speak":
            self.speech_player = SpeechOutputPlayer(
                output_device_name=self.speech_output_device_name,
                monitor=self.monitor_spoken_audio,
                on_event=self.emit,
            )

        print("Initialization complete.\n")

    def emit(self, event_type, payload=None):
        if callable(self.on_event):
            try:
                self.on_event(event_type, payload)
            except Exception:
                pass

    def recognize_arabic_offline(self, audio_array):
        return self.recognize_speech_offline(audio_array)

    def recognize_speech_offline(self, audio_array):
        if not self.asr:
            raise RuntimeError("Offline ASR is not initialized")
        base_kwargs = {"task": "transcribe", "language": (self.whisper_language or "ar")}
        guarded_kwargs = {
            **base_kwargs,
            "logprob_threshold": -1.0,
            "no_speech_threshold": 0.6,
            "compression_ratio_threshold": 2.4,
        }
        payload = {"array": audio_array.astype(np.float32), "sampling_rate": self.sample_rate}
        try:
            result = self.asr(payload, generate_kwargs=guarded_kwargs, return_timestamps=False)
        except (TypeError, ValueError):
            result = self.asr(payload, generate_kwargs=base_kwargs, return_timestamps=False)

        if isinstance(result, str):
            return result.strip()
        if isinstance(result, dict):
            return (result.get("text", "") or "").strip()
        try:
            return str(result).strip()
        except Exception:
            return ""

    def capture_audio(self):
        try:
            if self.selected_device is None:
                raise RuntimeError("No audio device selected")

            device_name = getattr(self.selected_device, "name", "<unknown>")
            print(f"Capturing audio from: {device_name}")
            if getattr(self.selected_device, "isloopback", False):
                print(
                    f"Loopback capture sample rate: {self.capture_sample_rate} Hz "
                    f"(ASR runs at {self.sample_rate} Hz)"
                )
            gate = self.mic_noise_gate if should_apply_mic_noise_gate(self.selected_device) else 0.0
            if gate > 0:
                print(f"Mic noise gate: {gate:.4f} RMS")
            print("-" * 50)

            processor = AudioChunkProcessor(
                chunk_duration=self.chunk_duration,
                input_sample_rate=self.capture_sample_rate,
                target_sample_rate=self.sample_rate,
                noise_gate_rms=gate,
                source_name=device_name,
            )
            block_duration = min(0.25, max(0.05, self.chunk_duration / 12.0))
            block_size = max(1, int(self.capture_sample_rate * block_duration))

            with self.selected_device.recorder(samplerate=self.capture_sample_rate) as recorder:
                while self.running:
                    audio_data = recorder.record(numframes=block_size)
                    for result in processor.append(audio_data, self.capture_sample_rate):
                        self._handle_capture_result(result)
                for result in processor.flush():
                    self._handle_capture_result(result)
        except Exception as exc:
            self.emit("error", f"Audio capture failed: {exc}")
            print(f"\nError capturing audio: {exc}")
            self.running = False

    def _handle_capture_result(self, result):
        self.emit("level", {"peak": result.peak, "rms": result.rms})
        if result.kind == "audio":
            self._silence_run = 0
            if self.mode == "speak" and self.speech_player and self.speech_player.is_playing:
                return
            self.audio_queue.put(result)
            return

        self._silence_run += 1
        if self.audio_debug:
            print(f"\nDropped chunk: {result.kind} peak={result.peak:.6f} rms={result.rms:.6f}")
        if (
            result.kind == DROP_DIGITAL_SILENCE
            and self._silence_run >= 5
            and (time.time() - self._last_audio_hint_time) > 10
        ):
            device_name = getattr(self.selected_device, "name", "<unknown>")
            if self.mode == "speak":
                hint = (
                    f"No speech detected from '{device_name}'. Check the mic and "
                    "Windows microphone privacy settings."
                )
            else:
                loopback_hint = ""
                if getattr(self.selected_device, "isloopback", False):
                    loopback_hint = (
                        " If this is a loopback device, ensure audio is playing through "
                        "that output and try CAPTURE_SAMPLE_RATE=48000."
                    )
                hint = (
                    f"No audio detected from '{device_name}'. Select the correct device "
                    f"and ensure Windows microphone permission is enabled.{loopback_hint}"
                )
            print(f"\n{hint}")
            self.emit("status", "no_audio")
            self.emit("hint", hint)
            self._last_audio_hint_time = time.time()

    def process_audio(self):
        while self.running or not self.audio_queue.empty():
            try:
                item = self.audio_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                audio_data, peak, rms = self._coerce_audio_item(item)
                if audio_data.size == 0:
                    continue

                if self.audio_debug:
                    self._debug_counter += 1
                    if self._debug_counter % 10 == 0:
                        print(f"\nAudio level: peak={peak:.6f} rms={rms:.6f}")

                started = time.time()
                self.emit("status", "transcribing")
                print("Transcribing (offline Whisper)...", end="\r")
                source_text = self.recognize_speech_offline(audio_data)
                elapsed = time.time() - started
                if elapsed > 2.0 and self.audio_debug:
                    print(f"\nASR time: {elapsed:.1f}s")

                if not source_text:
                    if self.running:
                        self.emit("status", "listening")
                    continue

                self.emit("source", source_text)
                self.emit("arabic", source_text)
                print(f"\nSource: {source_text}")

                self.emit("status", "translating")
                translated_text = self.translate_text(source_text)
                self.emit("target", translated_text)
                self.emit("english", translated_text)
                print(f"Target: {translated_text}")
                print("-" * 50)

                transcript_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "source_text": source_text,
                    "translated_text": translated_text,
                    "source_language": self.whisper_language,
                    "target_language": self.translation_target_language,
                    "mode": self.mode,
                    "arabic_text": source_text,
                    "english_text": translated_text,
                }
                self.transcripts.append(transcript_entry)
                self.emit("transcript", transcript_entry)

                if self.mode == "speak" and translated_text and self.speech_player:
                    self.emit("status", "speaking")
                    self.speech_player.enqueue(
                        translated_text,
                        self.translation_target_language,
                        self.speech_voice,
                    )
                elif self.running:
                    self.emit("status", "listening")
            except Exception as exc:
                hint = " (set OFFLINE_ONLY=0 to allow first-time model download)" if self.offline_only else ""
                self.emit("error", f"{exc}{hint}")
                print(f"\nProcessing error: {exc}{hint}")

    def _coerce_audio_item(self, item):
        if isinstance(item, AudioChunkResult):
            return item.samples, item.peak, item.rms

        if isinstance(item, tuple) and len(item) == 2:
            audio_data, capture_sr = item
        else:
            audio_data, capture_sr = item, self.sample_rate
        if capture_sr != self.sample_rate:
            audio_data = resample_audio(audio_data, capture_sr, self.sample_rate)
        peak = float(np.max(np.abs(audio_data))) if audio_data.size else 0.0
        rms = float(np.sqrt(np.mean(np.square(audio_data)))) if audio_data.size else 0.0
        if peak < 0.000001 and rms < 0.0000005:
            return np.asarray([], dtype=np.float32), peak, rms
        if peak > 0 and peak < 0.05:
            gain = min(200.0, 0.9 / peak)
            audio_data = (audio_data * gain).astype(np.float32, copy=False)
            peak = float(np.max(np.abs(audio_data))) if audio_data.size else 0.0
            rms = float(np.sqrt(np.mean(np.square(audio_data)))) if audio_data.size else 0.0
        return audio_data.astype(np.float32, copy=False), peak, rms

    def translate_text(self, source_text):
        translation = self.translator(source_text, max_length=512, truncation=True)
        return translation[0]["translation_text"]

    def start_background(self, enable_keyboard_shortcuts=False):
        if self.running:
            return
        self.running = True
        save_runtime_config(
            CONFIG_FILE,
            mic_noise_gate=self.mic_noise_gate,
            last_mode=self.mode,
            chunk_duration=self.chunk_duration,
        )
        if self.speech_player:
            self.speech_player.start()
        if enable_keyboard_shortcuts and self.interactive:
            self.setup_keyboard_shortcuts()
        self._capture_thread = threading.Thread(target=self.capture_audio, daemon=True)
        self._process_thread = threading.Thread(target=self.process_audio, daemon=True)
        self._capture_thread.start()
        self._process_thread.start()

    def stop_background(self):
        self.running = False
        if self.speech_player:
            self.speech_player.stop()

    def join_background(self, timeout_capture=2, timeout_process=5):
        if self._capture_thread:
            self._capture_thread.join(timeout=timeout_capture)
        if self._process_thread:
            self._process_thread.join(timeout=timeout_process)

    def run(self):
        if self.interactive:
            self.setup_keyboard_shortcuts()

        while True:
            self.start_background(enable_keyboard_shortcuts=False)
            try:
                while self.running:
                    if self.device_change_requested:
                        print("\nStopping current session for device change...")
                        self.running = False
                        break
                    time.sleep(0.1)
            except KeyboardInterrupt:
                print("\nStopping transcription...")
                self.running = False

            self.join_background(timeout_capture=2, timeout_process=5)

            if self.device_change_requested:
                self.device_change_requested = False
                if self.change_device_interactive():
                    print("\n" + "=" * 50)
                    print("RESUMING TRANSCRIPTION WITH NEW DEVICE")
                    print("=" * 50)
                    continue
                choice = input("\nContinue with current device? (y/n): ").strip().lower()
                if choice == "y":
                    continue
            break

        self.save_transcript()
        print("Transcription stopped.")

    def setup_keyboard_shortcuts(self):
        if not keyboard:
            return

        def on_device_change():
            self.device_change_requested = True
            print("\nDevice change requested. Press Ctrl+C to stop current session and change device.")

        keyboard.add_hotkey("ctrl+d", on_device_change)
        print("\nKeyboard shortcuts:")
        print("   Ctrl+D: Change audio device")
        print("   Ctrl+C: Stop transcription")

    def change_device_interactive(self):
        print("\n" + "=" * 50)
        print("CHANGE AUDIO DEVICE")
        print("=" * 50)

        new_device = select_audio_device()
        if new_device:
            self.selected_device = new_device
            save_device_config(new_device.name)
            print(f"\nDevice changed to: {new_device.name}")
            return True
        print("\nDevice change cancelled.")
        return False

    def save_transcript(self):
        if not self.transcripts:
            print("No transcripts to save.")
            return None

        try:
            transcript_dir = os.fspath(self.transcript_folder)
            os.makedirs(transcript_dir, exist_ok=True)
            timestamp = self.session_start_time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(transcript_dir, f"transcript_{timestamp}.txt")

            with open(filepath, "w", encoding="utf-8") as handle:
                handle.write("=" * 60 + "\n")
                handle.write("TRANSLITO — TRANSCRIPT\n")
                handle.write("=" * 60 + "\n")
                handle.write(f"Session Start: {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                handle.write(f"Session End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                handle.write(f"Mode: {self.mode}\n")
                handle.write(
                    f"Audio Device: {self.selected_device.name if self.selected_device else 'Unknown'}\n"
                )
                handle.write(f"Total Entries: {len(self.transcripts)}\n")
                handle.write("=" * 60 + "\n\n")

                for index, entry in enumerate(self.transcripts, 1):
                    entry_time = datetime.fromisoformat(entry["timestamp"]).strftime("%H:%M:%S")
                    source_text = entry.get("source_text", entry.get("arabic_text", ""))
                    translated_text = entry.get("translated_text", entry.get("english_text", ""))
                    source_language = entry.get("source_language", "source")
                    target_language = entry.get("target_language", "target")
                    handle.write(f"[{index:03d}] {entry_time}\n")
                    handle.write("-" * 40 + "\n")
                    handle.write(f"Source ({source_language}): {source_text}\n")
                    handle.write(f"Target ({target_language}): {translated_text}\n\n")

            print(f"\nTranscript saved to: {filepath}")
            print(f"   Total entries: {len(self.transcripts)}")
            self.last_saved_path = filepath
            return filepath
        except Exception as exc:
            print(f"\nError saving transcript: {exc}")
            return None


def select_audio_device(show_saved_device=True):
    print("\n" + "=" * 50)
    print("AUDIO DEVICE SELECTION")
    print("=" * 50)

    if not sc:
        print("No audio backend available.")
        return None

    saved_device_name = load_device_config() if show_saved_device else None
    saved_device = find_device_by_name(saved_device_name) if saved_device_name else None
    if saved_device:
        print(f"\nSaved Default Device: {saved_device.name}")
        print("   Press ENTER to use saved device, or select a different one below.")
    elif saved_device_name:
        print(f"\nSaved device '{saved_device_name}' not found. Please select a new device.")

    all_devices = sc.all_microphones(include_loopback=True)
    if not all_devices:
        print("No audio devices found.")
        return None

    loopback_devices = [device for device in all_devices if getattr(device, "isloopback", False)]
    microphone_devices = [device for device in all_devices if not getattr(device, "isloopback", False)]

    print("\nDESKTOP AUDIO (Loopback) Devices:")
    print("-" * 40)
    if loopback_devices:
        for index, device in enumerate(loopback_devices, 1):
            print(f"  {index}. {device.name}")
    else:
        print("  No loopback devices found")

    print("\nMICROPHONE Devices:")
    print("-" * 40)
    if microphone_devices:
        for index, device in enumerate(microphone_devices, len(loopback_devices) + 1):
            print(f"  {index}. {device.name}")
    else:
        print("  No microphone devices found")

    print("\nDefault Devices:")
    print("-" * 40)
    try:
        default_speaker = sc.default_speaker()
        if default_speaker:
            print(f"  Default Speaker: {default_speaker.name}")
    except Exception:
        pass
    try:
        default_mic = sc.default_microphone()
        if default_mic:
            print(f"  Default Microphone: {default_mic.name}")
    except Exception:
        pass

    print("\n" + "=" * 50)
    print("Select an audio device:")
    if saved_device:
        print("  - Press ENTER to use saved default device")
    print("  - For desktop audio, choose a loopback device")
    print("  - For microphone input, choose a microphone device")
    print("  - Enter 0 to try auto-detect desktop audio")
    print("  - Enter Q to quit")
    print("=" * 50)

    while True:
        try:
            prompt = "\nEnter device number (1-{})".format(len(all_devices))
            if saved_device:
                prompt += " or ENTER for default"
            prompt += ": "
            choice = input(prompt).strip()

            if choice.upper() == "Q":
                return None
            if choice == "" and saved_device:
                print(f"\nUsing saved device: {saved_device.name}")
                return saved_device

            choice_num = int(choice)
            if choice_num == 0:
                if loopback_devices:
                    selected = loopback_devices[0]
                    print(f"Selected: {selected.name}")
                    save_device_config(selected.name)
                    return selected
                print("No loopback devices found. Please select a microphone instead.")
                continue

            if 1 <= choice_num <= len(all_devices):
                if choice_num <= len(loopback_devices):
                    selected = loopback_devices[choice_num - 1]
                    device_type = "Desktop Audio (Loopback)"
                else:
                    selected = microphone_devices[choice_num - len(loopback_devices) - 1]
                    device_type = "Microphone"
                print(f"\nSelected: {selected.name} [{device_type}]")
                if not getattr(selected, "isloopback", False):
                    print("Note: Microphone selected - this captures your mic, not desktop audio.")
                confirm = input("Confirm selection? (y/n): ").strip().lower()
                if confirm == "y":
                    save_device_config(selected.name)
                    return selected
                print("Selection cancelled. Please choose again.")
            else:
                print(f"Invalid choice. Please enter a number between 1 and {len(all_devices)}.")
        except ValueError:
            print("Invalid input. Please enter a number or Q to quit.")
        except Exception as exc:
            print(f"Error: {exc}")
            return None


def main():
    print("=" * 50)
    print("Translito")
    print("=" * 50)

    require_dependencies()

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("\nUsage: python main.py")
        print("\nCommand-line mode (device selection in terminal).")
        print("GUI mode is available via gui.py.")
        sys.exit(0)

    try:
        saved_device_name = load_device_config()
        selected_device = None
        if saved_device_name:
            saved_device = find_device_by_name(saved_device_name)
            if saved_device:
                print(f"\nFound saved default device: {saved_device.name}")
                use_saved = input("Use saved device? (Y/n): ").strip().lower()
                if use_saved != "n":
                    selected_device = saved_device
                    print(f"Using saved device: {selected_device.name}")

        if selected_device is None:
            selected_device = select_audio_device()
            if selected_device is None:
                print("\nNo device selected. Exiting...")
                sys.exit(0)

        print("\n" + "=" * 50)
        print("Starting Transcription")
        print("=" * 50)

        transcriber = ArabicAudioTranscriber(selected_device=selected_device)
        transcriber.run()
    except KeyboardInterrupt:
        print("\nProgram interrupted by user.")
    except Exception as exc:
        print(f"\nFatal error: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
