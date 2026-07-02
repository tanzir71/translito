#!/usr/bin/env python3
"""
Arabic Desktop Audio Transcriber and Translator
Captures desktop audio, transcribes Arabic speech, and translates to English
"""

import warnings
warnings.filterwarnings("ignore")
warnings.filterwarnings("ignore", message=r"`return_token_timestamps` is deprecated.*", category=FutureWarning)
import sys
import json
from datetime import datetime
import os
import atexit
import configparser
import threading
import queue
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SUPPORT_DIR = os.environ.get(
    "DAT_APP_SUPPORT_DIR",
    os.path.join(
        os.path.expanduser("~"),
        "Library",
        "Application Support",
        "Desktop Audio Translator Menu Bar",
    ),
)
CONFIG_FILE = os.path.join(APP_SUPPORT_DIR, "config.ini")
TRANSCRIPT_DIR = os.path.join(APP_SUPPORT_DIR, "transcripts")
VIRTUAL_AUDIO_NAME_PARTS = (
    "blackhole",
    "soundflower",
    "loopback",
    "background music",
    "vb-cable",
    "audio hijack",
    "rogue amoeba",
    "virtual",
)

missing_packages = []
dependency_errors = {}
keyboard_error = None

def record_dependency_error(package_name, error):
    if package_name not in missing_packages:
        missing_packages.append(package_name)
    dependency_errors[package_name] = error

if os.environ.get("DAT_DISABLE_KEYBOARD", "").strip().lower() in {"1", "true", "yes", "on"}:
    keyboard = None
else:
    try:
        import keyboard
    except Exception as exc:
        keyboard_error = exc
        keyboard = None
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
    soundcard_warning = getattr(sc, "SoundcardRuntimeWarning", None)
    if soundcard_warning is not None:
        warnings.filterwarnings("ignore", category=soundcard_warning)
try:
    import numpy as np
except Exception as exc:
    np = None
    record_dependency_error("numpy", exc)
try:
    from transformers import pipeline
except Exception as exc:
    pipeline = None
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
    lines.append("Apple Silicon Macs can use Metal acceleration when PyTorch MPS is available.")
    lines.append("If model loading is slow, install a current torch build from the official PyTorch instructions.")
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
        for p in extra_missing:
            print(f"  - {p}")
        print("\nInstall:")
        print(f"  pip install {' '.join(extra_missing)}")

def load_device_config():
    """Load saved device configuration"""
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        if 'DEVICE' in config and 'name' in config['DEVICE']:
            return config['DEVICE']['name']
    return None

def save_device_config(device_name):
    """Save device configuration"""
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    if 'DEVICE' not in config:
        config['DEVICE'] = {}
    config['DEVICE']['name'] = device_name
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)
    print(f"Device '{device_name}' saved as default.")

def find_device_by_name(device_name):
    """Find audio device by name"""
    all_devices = sc.all_microphones(include_loopback=True)
    for device in all_devices:
        if device.name == device_name:
            return device
    return None

def is_desktop_audio_device(device):
    """Return True for loopback or virtual desktop-audio capture devices."""
    if getattr(device, "isloopback", False):
        return True
    name = getattr(device, "name", "").lower()
    return any(part in name for part in VIRTUAL_AUDIO_NAME_PARTS)

def device_type_label(device):
    return "Desktop/Virtual" if is_desktop_audio_device(device) else "Mic"

def no_audio_hint_for(device):
    if is_desktop_audio_device(device):
        return (
            "For desktop audio on macOS, route system output to a Multi-Output Device "
            "that includes BlackHole, then select the BlackHole input here. "
            "If the device is present but silent, try CAPTURE_SAMPLE_RATE=48000."
        )
    return (
        "Grant Microphone access to Terminal or Python in System Settings > "
        "Privacy & Security > Microphone, then restart the app."
    )

def select_torch_runtime():
    if torch is None:
        return -1, None, "CPU"
    if torch.cuda.is_available():
        return 0, torch.float16, "CUDA"
    mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
    if mps_backend and mps_backend.is_available():
        return "mps", None, "Apple Metal (MPS)"
    return -1, None, "CPU"

class ArabicAudioTranscriber:
    def __init__(self, selected_device=None, on_event=None, interactive=True, asr_language=None, translation_model=None):
        """Initialize the transcriber with audio capture and translation models"""
        self.on_event = on_event
        self.interactive = interactive
        self.log("Initializing Arabic Audio Transcriber...")

        # Store selected device
        self.selected_device = selected_device

        # Initialize transcript storage
        self.transcripts = []
        self.session_start_time = datetime.now()

        # Register cleanup function to save transcripts on exit
        atexit.register(self.save_transcript)

        # Keyboard shortcut flag
        self.device_change_requested = False

        self.offline_only = os.environ.get("OFFLINE_ONLY", "0").strip() == "1"
        self.asr_language = (asr_language or os.environ.get("ASR_LANGUAGE", "ar-AR")).strip() or "ar-AR"
        self.whisper_language = (self.asr_language.split("-")[0].strip().lower() or "ar")
        self.audio_debug = os.environ.get("AUDIO_DEBUG", "0").strip() == "1"
        try:
            capture_sr_env = int(os.environ.get("CAPTURE_SAMPLE_RATE", "0").strip() or "0")
        except Exception:
            capture_sr_env = 0
        if capture_sr_env > 0:
            self.capture_sample_rate = capture_sr_env
        else:
            self.capture_sample_rate = 48000 if is_desktop_audio_device(self.selected_device) else 16000

        self.torch_device, self.torch_dtype, self.torch_runtime = select_torch_runtime()
        if self.torch_runtime == "CUDA":
            self.log("GPU detected (CUDA). Using GPU acceleration.")
        elif self.torch_runtime == "Apple Metal (MPS)":
            self.log("Apple Silicon acceleration detected (MPS). Using local Metal acceleration.")
        else:
            if torch and "+cpu" in getattr(torch, "__version__", ""):
                self.log("Hardware acceleration not available (CPU-only torch build). Using CPU.")
            else:
                self.log("Hardware acceleration not available. Using CPU.")

        # Initialize offline ASR (Whisper via transformers)
        self.asr = None
        whisper_model = os.environ.get("WHISPER_MODEL", "openai/whisper-small").strip()
        self.log("Loading offline ASR model (Whisper)...")
        if self.offline_only:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            asr_kwargs = {
                "model": whisper_model,
                "device": self.torch_device,
            }
            if self.torch_dtype is not None:
                asr_kwargs["torch_dtype"] = self.torch_dtype
            try:
                self.asr = self.load_pipeline("automatic-speech-recognition", **asr_kwargs)
            except TypeError:
                asr_kwargs.pop("torch_dtype", None)
                self.asr = self.load_pipeline("automatic-speech-recognition", **asr_kwargs)
            try:
                self.asr.feature_extractor.return_attention_mask = True
            except Exception:
                pass
            self.log("Offline ASR ready.")
        except Exception as e:
            self.log(f"Failed to initialize offline ASR: {e}")
            if self.offline_only:
                self.log("Offline-only is enabled. Set OFFLINE_ONLY=0 once to allow the model to download, then rerun.")
            raise

        # Initialize translation pipeline (Helsinki-NLP)
        self.log("Loading translation model (this may take a moment on first run)...")
        translation_model_name = (translation_model or os.environ.get("TRANSLATION_MODEL", "Helsinki-NLP/opus-mt-ar-en")).strip()
        self.translator = self.load_pipeline(
            "translation",
            model=translation_model_name,
            device=self.torch_device
        )

        # Audio settings
        self.sample_rate = 16000  # 16kHz for speech recognition
        default_chunk = 3
        try:
            self.chunk_duration = float(os.environ.get("CHUNK_DURATION", str(default_chunk)).strip())
        except Exception:
            self.chunk_duration = float(default_chunk)

        # Threading components
        self.audio_queue = queue.Queue()
        self.running = False
        self._silence_run = 0
        self._empty_transcript_run = 0
        self._last_audio_hint_time = 0.0
        self._last_no_speech_time = 0.0
        self._has_seen_audio = False
        self._debug_counter = 0

        self.log("Initialization complete.")

    def load_pipeline(self, task, **kwargs):
        try:
            return pipeline(task, **kwargs)
        except Exception as exc:
            if kwargs.get("device") == "mps":
                self.log(f"MPS model load failed ({exc}). Falling back to CPU.")
                self.torch_device = -1
                self.torch_dtype = None
                self.torch_runtime = "CPU"
                kwargs["device"] = -1
                kwargs.pop("torch_dtype", None)
                return pipeline(task, **kwargs)
            raise

    def log(self, message):
        if callable(getattr(self, "on_event", None)):
            self.emit("log", message)
        else:
            print(message)

    def console(self, *args, **kwargs):
        if not callable(getattr(self, "on_event", None)):
            print(*args, **kwargs)

    def resample_audio(self, audio_array, original_sample_rate, target_sample_rate):
        if original_sample_rate == target_sample_rate:
            return audio_array.astype(np.float32, copy=False)
        if audio_array is None or audio_array.size == 0:
            return np.asarray([], dtype=np.float32)
        duration_s = float(audio_array.shape[0]) / float(original_sample_rate)
        target_len = int(round(duration_s * float(target_sample_rate)))
        if target_len <= 1:
            return np.asarray([], dtype=np.float32)
        x = audio_array.astype(np.float32, copy=False)
        original_positions = np.arange(x.shape[0], dtype=np.float64)
        target_positions = np.linspace(0, x.shape[0] - 1, num=target_len, dtype=np.float64)
        y = np.interp(target_positions, original_positions, x).astype(np.float32)
        return y

    def emit(self, event_type, payload=None):
        if callable(self.on_event):
            try:
                self.on_event(event_type, payload)
            except Exception:
                pass

    def recognize_arabic_offline(self, audio_array):
        if not self.asr:
            raise RuntimeError("Offline ASR is not initialized")
        result = self.asr(
            {"array": audio_array.astype(np.float32), "sampling_rate": self.sample_rate},
            generate_kwargs={"task": "transcribe", "language": (self.whisper_language or "ar")},
            return_timestamps=False,
        )
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, dict):
            text = result.get("text", "")
            return (text or "").strip()
        try:
            return str(result).strip()
        except Exception:
            return ""

    def capture_audio(self):
        """Continuously capture audio from selected device and add to queue"""
        try:
            if self.selected_device is None:
                raise RuntimeError("No audio device selected")

            self.log(f"Capturing audio from: {self.selected_device.name}")
            if is_desktop_audio_device(self.selected_device):
                self.log(f"Desktop audio capture sample rate: {self.capture_sample_rate} Hz (ASR runs at {self.sample_rate} Hz)")
            self.log("Capture started.")

            # Open recorder for the selected device
            with self.selected_device.recorder(samplerate=self.capture_sample_rate) as mic:
                while self.running:
                    # Capture audio chunk
                    chunk_size = int(self.capture_sample_rate * self.chunk_duration)
                    audio_data = mic.record(numframes=chunk_size)

                    # Convert stereo to mono if necessary
                    if len(audio_data.shape) > 1:
                        audio_data = np.mean(audio_data, axis=1)

                    # Add to queue for processing
                    self.audio_queue.put((audio_data, self.capture_sample_rate))

        except Exception as e:
            self.emit("error", f"Error capturing audio: {e}")
            self.log(f"Error capturing audio: {e}")
            self.running = False

    def process_audio(self):
        """Process audio chunks from queue: transcribe and translate"""
        while self.running or not self.audio_queue.empty():
            try:
                # Get audio chunk from queue (timeout prevents hanging)
                item = self.audio_queue.get(timeout=1)
                if isinstance(item, tuple) and len(item) == 2:
                    audio_data, capture_sr = item
                else:
                    audio_data, capture_sr = item, self.sample_rate
                if capture_sr != self.sample_rate:
                    audio_data = self.resample_audio(audio_data, capture_sr, self.sample_rate)

                try:
                    # Transcribe Arabic audio
                    self.console("Listening...", end="\r")
                    peak = float(np.max(np.abs(audio_data))) if audio_data.size else 0.0
                    rms = float(np.sqrt(np.mean(np.square(audio_data)))) if audio_data.size else 0.0

                    if self.audio_debug:
                        self._debug_counter += 1
                        if self._debug_counter % 10 == 0:
                            self.log(f"Audio level: peak={peak:.6f} rms={rms:.6f}")

                    if peak < 0.000001 and rms < 0.0000005:
                        self._silence_run += 1
                        if self._silence_run >= 2 and (time.time() - self._last_audio_hint_time) > 8:
                            device_name = getattr(self.selected_device, "name", "<unknown>")
                            hint = no_audio_hint_for(self.selected_device)
                            self.emit("no_audio", {
                                "device_name": device_name,
                                "hint": hint,
                                "peak": peak,
                                "rms": rms,
                            })
                            self.log(f"No audio detected from '{device_name}'. {hint}")
                            self._last_audio_hint_time = time.time()
                        continue

                    if self._silence_run > 0 or not self._has_seen_audio:
                        self.emit("audio_detected", {"peak": peak, "rms": rms})
                    self._has_seen_audio = True
                    self._silence_run = 0

                    if peak > 0 and peak < 0.05:
                        gain = min(200.0, 0.9 / peak)
                        audio_data = audio_data * gain
                    started = time.time()
                    self.console("Transcribing (offline Whisper)...", end="\r")
                    self.emit("status", "transcribing")
                    arabic_text = self.recognize_arabic_offline(audio_data)

                    elapsed = time.time() - started
                    if elapsed > 2.0 and self.audio_debug:
                        self.log(f"ASR time: {elapsed:.1f}s")

                    if not arabic_text:
                        self._empty_transcript_run += 1
                        if (time.time() - self._last_no_speech_time) > 10:
                            self.emit("no_speech", "Audio is coming in, but no speech was recognized yet.")
                            self._last_no_speech_time = time.time()
                        continue

                    self._empty_transcript_run = 0
                    self.emit("arabic", arabic_text)
                    self.console(f"\n🎤 Arabic: {arabic_text}")

                    # Translate to English
                    self.emit("status", "translating")
                    translation = self.translator(
                        arabic_text,
                        max_length=512,
                        truncation=True
                    )
                    english_text = translation[0]['translation_text']
                    self.emit("english", english_text)
                    self.console(f"🔤 English: {english_text}")
                    self.console("-" * 50)

                    # Store transcript entry
                    transcript_entry = {
                        'timestamp': datetime.now().isoformat(),
                        'arabic_text': arabic_text,
                        'english_text': english_text
                    }
                    self.transcripts.append(transcript_entry)
                    self.emit("transcript", transcript_entry)

                except Exception as e:
                    hint = ""
                    if self.offline_only:
                        hint = " (set OFFLINE_ONLY=0 to allow first-time model download)"
                    self.emit("error", f"{e}{hint}")
                    self.log(f"Offline ASR error: {e}{hint}")
                    continue

            except queue.Empty:
                continue
            except Exception as e:
                self.emit("error", f"Error processing audio: {e}")
                self.log(f"Error processing audio: {e}")

    def start_background(self, enable_keyboard_shortcuts=False):
        if self.running:
            return
        self.running = True
        if enable_keyboard_shortcuts and self.interactive:
            self.setup_keyboard_shortcuts()
        self._capture_thread = threading.Thread(target=self.capture_audio, daemon=True)
        self._process_thread = threading.Thread(target=self.process_audio, daemon=True)
        self._capture_thread.start()
        self._process_thread.start()

    def stop_background(self):
        self.running = False

    def join_background(self, timeout_capture=2, timeout_process=5):
        t1 = getattr(self, "_capture_thread", None)
        t2 = getattr(self, "_process_thread", None)
        if t1:
            t1.join(timeout=timeout_capture)
        if t2:
            t2.join(timeout=timeout_process)

    def run(self):
        """Main run loop with threading for simultaneous capture and processing"""
        self.running = True
        if self.interactive:
            self.setup_keyboard_shortcuts()

        while True:
            self.start_background(enable_keyboard_shortcuts=False)

            try:
                # Keep main thread alive and check for device change requests
                while self.running:
                    if self.device_change_requested:
                        print("\n\nStopping current session for device change...")
                        self.running = False
                        break
                    time.sleep(0.1)
            except KeyboardInterrupt:
                print("\n\nStopping transcription...")
                self.running = False

            # Wait for threads to finish
            self.join_background(timeout_capture=2, timeout_process=5)

            # Handle device change request
            if self.device_change_requested:
                self.device_change_requested = False
                if self.change_device_interactive():
                    # Restart with new device
                    self.running = True
                    print("\n" + "=" * 50)
                    print("RESUMING TRANSCRIPTION WITH NEW DEVICE")
                    print("=" * 50)
                    continue
                else:
                    # User cancelled, ask if they want to continue with current device
                    choice = input("\nContinue with current device? (y/n): ").strip().lower()
                    if choice == 'y':
                        self.running = True
                        continue
                    else:
                        break
            else:
                # Normal exit
                break

        # Save transcript before stopping
        self.save_transcript()
        self.log("Transcription stopped.")

    def setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for device selection"""
        if not keyboard:
            if keyboard_error:
                print(f"\n⚠️ Keyboard shortcuts unavailable: {keyboard_error}")
            print("   Use Ctrl+C to stop transcription, then restart to change devices.")
            return
        def on_device_change():
            self.device_change_requested = True
            print("\n🔄 Device change requested. Press Cmd+C to stop current session and change device.")

        try:
            keyboard.add_hotkey('command+d', on_device_change)
            print("\n⌨️  Keyboard shortcuts:")
            print("   Cmd+D: Change audio device")
            print("   Cmd+C: Stop transcription")
        except Exception as e:
            print(f"\n⚠️ Keyboard shortcuts unavailable: {e}")
            print("   Grant Accessibility access to Terminal or Python to enable Cmd+D.")

    def change_device_interactive(self):
        """Interactive device change during runtime"""
        print("\n" + "=" * 50)
        print("CHANGE AUDIO DEVICE")
        print("=" * 50)

        new_device = select_audio_device()
        if new_device:
            self.selected_device = new_device
            save_device_config(new_device.name)
            print(f"\n✅ Device changed to: {new_device.name}")
            return True
        else:
            print("\n❌ Device change cancelled.")
            return False

    def save_transcript(self):
        """Save all transcripts to a text file"""
        if not self.transcripts:
            self.log("No transcripts to save.")
            return

        try:
            # Create transcripts directory if it doesn't exist
            transcript_dir = TRANSCRIPT_DIR
            if not os.path.exists(transcript_dir):
                os.makedirs(transcript_dir)

            # Generate filename with timestamp
            timestamp = self.session_start_time.strftime("%Y%m%d_%H%M%S")
            filename = f"transcript_{timestamp}.txt"
            filepath = os.path.join(transcript_dir, filename)

            # Save to text file
            with open(filepath, 'w', encoding='utf-8') as f:
                # Write session header
                f.write("=" * 60 + "\n")
                f.write("ARABIC AUDIO TRANSCRIPTION SESSION\n")
                f.write("=" * 60 + "\n")
                f.write(f"Session Start: {self.session_start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Session End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Audio Device: {self.selected_device.name if self.selected_device else 'Unknown'}\n")
                f.write(f"Total Entries: {len(self.transcripts)}\n")
                f.write("=" * 60 + "\n\n")

                # Write each transcript entry
                for i, entry in enumerate(self.transcripts, 1):
                    entry_time = datetime.fromisoformat(entry['timestamp']).strftime('%H:%M:%S')
                    f.write(f"[{i:03d}] {entry_time}\n")
                    f.write("-" * 40 + "\n")
                    f.write(f"🎤 Arabic:  {entry['arabic_text']}\n")
                    f.write(f"🔤 English: {entry['english_text']}\n")
                    f.write("\n")

            self.log(f"Transcript saved to: {filepath}")
            self.log(f"Total entries: {len(self.transcripts)}")

        except Exception as e:
            self.emit("error", f"Error saving transcript: {e}")
            self.log(f"Error saving transcript: {e}")

def select_audio_device(show_saved_device=True):
    """Interactive device selector"""
    print("\n" + "=" * 50)
    print("AUDIO DEVICE SELECTION")
    print("=" * 50)

    # Check for saved device
    saved_device_name = load_device_config() if show_saved_device else None
    saved_device = None
    if saved_device_name:
        saved_device = find_device_by_name(saved_device_name)
        if saved_device:
            print(f"\n💾 Saved Default Device: {saved_device.name}")
            print("   Press ENTER to use saved device, or select a different one below.")
        else:
            print(f"\n⚠️  Saved device '{saved_device_name}' not found. Please select a new device.")

    # Get all available microphones including loopback devices
    all_devices = sc.all_microphones(include_loopback=True)

    if not all_devices:
        print("No audio devices found!")
        return None

    # Separate devices by type
    desktop_devices = []
    microphone_devices = []

    for device in all_devices:
        if is_desktop_audio_device(device):
            desktop_devices.append(device)
        else:
            microphone_devices.append(device)

    # Display devices
    print("\n📢 DESKTOP AUDIO / VIRTUAL Devices:")
    print("-" * 40)
    if desktop_devices:
        for i, device in enumerate(desktop_devices):
            print(f"  {i + 1}. {device.name}")
    else:
        print("  No desktop/virtual devices found")

    print("\n🎤 MICROPHONE Devices:")
    print("-" * 40)
    if microphone_devices:
        for i, device in enumerate(microphone_devices):
            idx = len(desktop_devices) + i + 1
            print(f"  {idx}. {device.name}")
    else:
        print("  No microphone devices found")

    # Get default devices for reference
    print("\n💡 Default Devices:")
    print("-" * 40)
    try:
        default_speaker = sc.default_speaker()
        if default_speaker:
            print(f"  Default Speaker: {default_speaker.name}")
    except:
        pass

    try:
        default_mic = sc.default_microphone()
        if default_mic:
            print(f"  Default Microphone: {default_mic.name}")
    except:
        pass

    # Let user select
    print("\n" + "=" * 50)
    print("Select an audio device:")
    if saved_device:
        print("  • Press ENTER to use saved default device")
    print("  • For desktop audio (YouTube, music, calls), choose BlackHole or another virtual device")
    print("  • For microphone input, choose a microphone device")
    print("  • Enter 0 to try auto-detect desktop audio")
    print("  • Enter Q to quit")
    print("=" * 50)

    while True:
        try:
            prompt = "\nEnter device number (1-{})" + (" or ENTER for default" if saved_device else "") + ": "
            choice = input(prompt.format(len(all_devices))).strip()

            if choice.upper() == 'Q':
                return None

            # Handle ENTER for saved device
            if choice == "" and saved_device:
                print(f"\nUsing saved device: {saved_device.name}")
                return saved_device

            choice_num = int(choice)

            if choice_num == 0:
                # Auto-detect desktop audio
                print("\nAuto-detecting desktop audio device...")
                if desktop_devices:
                    selected = desktop_devices[0]
                    print(f"Selected: {selected.name}")
                    return selected
                else:
                    print("No desktop/virtual devices found. Install BlackHole or select a microphone instead.")
                    continue

            if 1 <= choice_num <= len(all_devices):
                # Map choice to device
                if choice_num <= len(desktop_devices):
                    selected = desktop_devices[choice_num - 1]
                else:
                    mic_idx = choice_num - len(desktop_devices) - 1
                    selected = microphone_devices[mic_idx]

                device_type = device_type_label(selected)
                print(f"\nSelected: {selected.name} [{device_type}]")

                if not is_desktop_audio_device(selected):
                    print("⚠️  Note: Microphone selected - this will capture your mic, not desktop audio")

                confirm = input("Confirm selection? (y/n): ").strip().lower()
                if confirm == 'y':
                    # Save the selected device as default
                    save_device_config(selected.name)
                    return selected
                else:
                    print("Selection cancelled. Please choose again.")
            else:
                print(f"Invalid choice. Please enter a number between 1 and {len(all_devices)}")

        except ValueError:
            print("Invalid input. Please enter a number or 'Q' to quit.")
        except Exception as e:
            print(f"Error: {e}")
            return None

def main():
    """Main entry point"""
    print("=" * 50)
    print("Desktop Audio Translator")
    print("=" * 50)

    require_dependencies()

    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("\nUsage: python main.py")
        print("\nCommand-line mode (device selection in terminal).")
        print("GUI mode is available via gui.py.")
        sys.exit(0)

    try:
        # Check for saved device first
        saved_device_name = load_device_config()
        selected_device = None

        if saved_device_name:
            saved_device = find_device_by_name(saved_device_name)
            if saved_device:
                print(f"\n💾 Found saved default device: {saved_device.name}")
                use_saved = input("Use saved device? (Y/n): ").strip().lower()
                if use_saved != 'n':
                    selected_device = saved_device
                    print(f"✅ Using saved device: {selected_device.name}")

        # If no saved device or user chose not to use it, show device selector
        if selected_device is None:
            selected_device = select_audio_device()

            if selected_device is None:
                print("\nNo device selected. Exiting...")
                sys.exit(0)

        # Create and run transcriber with selected device
        print("\n" + "=" * 50)
        print("Starting Transcription")
        print("=" * 50)

        transcriber = ArabicAudioTranscriber(selected_device=selected_device)
        transcriber.run()

    except KeyboardInterrupt:
        print("\n\nProgram interrupted by user.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
