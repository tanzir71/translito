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
from uuid import uuid4
import warnings

from native_tls import configure_native_tls

configure_native_tls()

warnings.filterwarnings("ignore")
warnings.filterwarnings(
    "ignore",
    message=r"`return_token_timestamps` is deprecated.*",
    category=FutureWarning,
)

from app_config import (
    CONFIG_FILE,
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
from engines.postprocess import postprocess
from engines.cancellation import generation_scope
from model_loading import GLOBAL_MODEL_MANAGER
from speech_output import SpeechOutputPlayer
from windows_audio import audio_com_context


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
    if getattr(sys, "frozen", False):
        lines.append("The installed Translito runtime is incomplete or incompatible.")
        lines.append("Check free space on the installation drive, then close Translito")
        lines.append("and reinstall using the latest Windows installer.")
        return "\n".join(lines)

    lines.append("Install or repair dependencies:")
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


@audio_com_context()
def find_device_by_name(device_name):
    if not sc:
        return None
    for device in sc.all_microphones(include_loopback=True):
        if device.name == device_name:
            return device
    return None


def translation_target_from_model(model_name, fallback="en"):
    if (model_name or "").startswith(("translategemma:", "cloud:")):
        return model_name.rsplit(":", 1)[-1]
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
        conversation=None,
        recognizer=None,
        translator_engine=None,
        glossary=None,
        asr_preset=None,
        engine_settings=None,
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
        self.asr_preset = asr_preset or runtime_config.asr_preset
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
        self._stop_event = threading.Event()
        self._last_backlog_hint_time = 0.0
        self._last_empty_text_hint_time = 0.0
        self.running = False
        self._silence_run = 0
        self._last_audio_hint_time = 0.0
        self._debug_counter = 0
        self._capture_thread = None
        self._process_thread = None
        self.speech_player = None
        self.conversation = conversation
        self.conversation_pipeline = None
        self.live_pipeline = None
        from engines.settings import load_engine_settings
        self.engine_settings = engine_settings or load_engine_settings()
        self.recognition_router = self.translation_router = None
        self._one_way_context = []

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
            if hasattr(self.asr, "beam_size"):
                self.asr.beam_size = {"fast": 1, "balanced": 3, "best": 5}.get(self.asr_preset, 3)
            self.translator = loaded_models.translator
            self.loaded_translator_engine = getattr(loaded_models, "translator_engine", None)
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

        if conversation is not None and not getattr(conversation, "one_way", False):
            from engines.asr_local import LocalConversationRecognizer
            from engines.conversation_pipeline import ConversationPipeline
            from engines.glossary import Glossary
            from engines.mt_quality import LocalQualityTranslator
            glossary = glossary or Glossary()
            recognizer = recognizer or LocalConversationRecognizer(
                self.asr, other_language=conversation.other_language, offline_only=self.offline_only,
                glossary=glossary, on_event=self.emit,
                device="cpu" if self.torch_device == -1 else f"cuda:{self.torch_device}",
            )
            translator_engine = translator_engine or self.loaded_translator_engine or LocalQualityTranslator(
                offline_only=self.offline_only, device=self.torch_device,
                on_hint=lambda text: self.emit("hint", text))
            if hasattr(translator_engine, "models") and self.translation_model_name.startswith("Helsinki-NLP/"):
                translator_engine.models[self.translation_model_name] = self.translator
            from engines.registry import build_session_routers
            from engines.settings import load_engine_settings
            conversation_lid = getattr(recognizer, "lid", None)
            recognizer, translator_engine = build_session_routers(
                recognizer, translator_engine, self.engine_settings,
                offline_only=self.offline_only, on_event=self.emit)
            self.conversation_pipeline = ConversationPipeline(
                recognizer, translator_engine, conversation, mode=self.mode, emit=self.emit,
                transcripts=self.transcripts, stop_event=self._stop_event,
                speech_player=self.speech_player, voice=self.speech_voice, glossary=glossary)
            from engines.registry import configured_live_interpreter
            interpreter = configured_live_interpreter(self.engine_settings, offline_only=self.offline_only, on_event=self.emit)
            if interpreter is not None:
                from engines.live_pipeline import LiveConversationPipeline
                self.live_pipeline = LiveConversationPipeline(self.conversation_pipeline, interpreter,
                    lid=conversation_lid, noise_gate=self.mic_noise_gate if self.mode == "speak" else 0)
                self.conversation_pipeline = self.live_pipeline
        else:
            if self.engine_settings.profile == "live-preview":
                self.emit("hint", "Live Translate uses English plus one other conversation language. Advanced one-way mode continues with Free.")
            from engines.asr_local import LocalOneWayRecognizer
            from engines.glossary import Glossary
            from engines.mt_quality import LocalQualityTranslator
            from engines.registry import build_session_routers
            from engines.settings import load_engine_settings
            self.glossary = glossary or Glossary()
            recognizer = recognizer or LocalOneWayRecognizer(
                self._recognize_speech_local, self.whisper_language, glossary=self.glossary)
            translator_engine = translator_engine or self.loaded_translator_engine or LocalQualityTranslator(
                offline_only=self.offline_only, device=self.torch_device,
                on_hint=lambda text: self.emit("hint", text))
            if hasattr(translator_engine, "models") and self.translation_model_name.startswith("Helsinki-NLP/"):
                translator_engine.models[self.translation_model_name] = self.translator
            self.recognition_router, self.translation_router = build_session_routers(
                recognizer, translator_engine, self.engine_settings,
                offline_only=self.offline_only, on_event=self.emit)

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
        router = getattr(self, "recognition_router", None)
        if router is not None:
            result = router.transcribe(audio_array, self.sample_rate, hint_language=self.whisper_language,
                                       stop_event=self._stop_event, prompt=self.glossary.hotwords())
            text = postprocess(result.text).text
            return self.glossary.restore_english(text)[0] if self.whisper_language == "ar" else text
        return self._recognize_speech_local(audio_array)

    def _recognize_speech_local(self, audio_array):
        if not self.asr:
            raise RuntimeError("Offline ASR is not initialized")
        if hasattr(self.asr, "transcribe"):
            text = self.asr.transcribe(
                audio_array.astype(np.float32),
                language=(self.whisper_language or "ar"),
                stop_event=getattr(self, "_stop_event", None),
            )
            return postprocess(text).text
        duration = len(audio_array) / self.sample_rate
        generate_kwargs = {
            "task": "transcribe",
            "language": (self.whisper_language or "ar"),
            "num_beams": 1,
            "do_sample": False,
            "use_cache": True,
            "max_new_tokens": max(32, min(256, int(duration * 16))),
        }
        stopping_criteria = self._generation_stopping_criteria()
        if stopping_criteria is not None:
            generate_kwargs["stopping_criteria"] = stopping_criteria
        payload = {"raw": audio_array.astype(np.float32), "sampling_rate": self.sample_rate}
        # Live chunks are short-form input. Long-form silence thresholds can fail
        # after decoding and previously caused the entire chunk to be decoded twice.
        result = self.asr(payload, generate_kwargs=generate_kwargs, return_timestamps=False)

        if isinstance(result, str):
            return postprocess(result).text
        if isinstance(result, dict):
            return postprocess(result.get("text", "") or "").text
        try:
            return postprocess(str(result)).text
        except Exception:
            return ""

    def _generation_stopping_criteria(self):
        stop_event = getattr(self, "_stop_event", None)
        if stop_event is None:
            return None
        from transformers import StoppingCriteria, StoppingCriteriaList

        class StopRequested(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return stop_event.is_set()

        return StoppingCriteriaList([StopRequested()])

    def capture_audio(self):
        try:
            with audio_com_context():
                self._capture_audio_initialized()
        except Exception as exc:
            self.emit("error", f"Audio capture failed: {exc}")
            print(f"\nError capturing audio: {exc}")
            self.running = False

    def _capture_audio_initialized(self):
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

        processor = self.create_audio_processor()
        live = getattr(self, "live_pipeline", None)
        block_duration = .1 if live is not None else min(0.25, max(0.05, self.chunk_duration / 12.0))
        block_size = max(1, int(self.capture_sample_rate * block_duration))

        with self.selected_device.recorder(samplerate=self.capture_sample_rate) as recorder:
            while self.running:
                audio_data = recorder.record(numframes=block_size)
                self.emit("level", {
                    "peak": float(np.max(np.abs(audio_data))) if audio_data.size else 0.0,
                    "rms": float(np.sqrt(np.mean(np.square(audio_data)))) if audio_data.size else 0.0,
                })
                if live is not None:
                    live.push_capture(audio_data, self.capture_sample_rate)
                for result in processor.append(audio_data, self.capture_sample_rate):
                    self._handle_capture_result(result)
            for result in processor.flush():
                self._handle_capture_result(result)

    def create_audio_processor(self, sample_rate=None):
        """Use identical capture preprocessing for live audio and evaluation."""
        return AudioChunkProcessor(
            chunk_duration=self.chunk_duration,
            input_sample_rate=sample_rate or self.capture_sample_rate,
            target_sample_rate=self.sample_rate,
            noise_gate_rms=(self.mic_noise_gate
                            if should_apply_mic_noise_gate(self.selected_device) else 0.0),
            source_name=getattr(self.selected_device, "name", "Evaluation audio"),
            on_speech=self.notify_capture_speech,
        )

    def notify_capture_speech(self, timestamp):
        pipeline = getattr(self, "conversation_pipeline", None)
        if pipeline is not None:
            pipeline.notify_speech(timestamp)

    def _handle_capture_result(self, result):
        if self._stop_event.is_set():
            return
        self.emit("level", {"peak": result.peak, "rms": result.rms})
        if result.kind == "audio":
            self._silence_run = 0
            live = getattr(self, "live_pipeline", None)
            if live is not None:
                result = live.mark_chunk(result)
            self.audio_queue.put_nowait(result)
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
            elif getattr(self.selected_device, "is_process_loopback", False):
                hint = (
                    f"No audio from '{device_name}'. Start playback in that app, "
                    "or refresh and select it again if it restarted. All apps excludes Translito's own audio."
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
            transcript_entry = None
            if self._stop_event.is_set():
                break
            try:
                item = self.audio_queue.get(timeout=0.2)
            except queue.Empty:
                pipeline = getattr(self, "conversation_pipeline", None)
                if pipeline is not None:
                    pipeline.poll()
                continue

            try:
                audio_data, peak, rms = self._coerce_audio_item(item)
                if audio_data.size == 0:
                    continue
                captured_at = getattr(item, "captured_at", None)
                lag = max(0.0, time.monotonic() - captured_at) if captured_at is not None else 0.0
                self.emit("lag", {"seconds": lag, "queued_segments": self.audio_queue.qsize()})
                if lag > 10 and time.monotonic() - self._last_backlog_hint_time > 10:
                    self.emit("hint", f"Behind by {lag:.0f}s. Speech is being kept; choose Fast "
                              "or enable a free cloud recognizer to reduce the delay.")
                    self._last_backlog_hint_time = time.monotonic()
                pipeline = getattr(self, "conversation_pipeline", None)
                if pipeline is not None:
                    chunk = item if isinstance(item, AudioChunkResult) else AudioChunkResult(
                        "audio", audio_data, self.sample_rate, peak, rms)
                    pipeline.feed(chunk)
                    pipeline.poll()
                    continue

                if self.audio_debug:
                    self._debug_counter += 1
                    if self._debug_counter % 10 == 0:
                        print(f"\nAudio level: peak={peak:.6f} rms={rms:.6f}")

                started = time.time()
                self.emit("status", "transcribing")
                print("Transcribing (offline Whisper)...", end="\r")
                source_text = self.recognize_speech_offline(audio_data)
                if self._stop_event.is_set():
                    continue
                elapsed = time.time() - started
                if elapsed > 2.0 and self.audio_debug:
                    print(f"\nASR time: {elapsed:.1f}s")

                if not source_text:
                    if time.monotonic() - self._last_empty_text_hint_time > 10:
                        self.emit(
                            "hint",
                            "Audio was received, but no speech was recognized. Check that "
                            "the selected source language matches the audio being played.",
                        )
                        self._last_empty_text_hint_time = time.monotonic()
                    if self.running:
                        self.emit("status", "listening")
                    continue

                self.emit("source", source_text)
                self.emit("arabic", source_text)
                print(f"\nSource: {source_text}")

                transcript_entry = {
                    "id": uuid4().hex,
                    "timestamp": datetime.now().isoformat(),
                    "source_text": source_text,
                    "translated_text": "",
                    "translation_pending": True,
                    "source_language": self.whisper_language,
                    "target_language": self.translation_target_language,
                    "mode": self.mode,
                    "arabic_text": source_text,
                    "english_text": "",
                    "captured_at": captured_at,
                    "speech_end_at": (captured_at - item.endpoint_delay_s
                                      if captured_at is not None and getattr(item, "endpoint_delay_s", None) is not None
                                      else None),
                }
                self.transcripts.append(transcript_entry)
                self.emit("transcript", transcript_entry.copy())

                self.emit("status", "translating")
                translated_text = self.translate_text(source_text)
                transcript_entry["translation_pending"] = False
                if self._stop_event.is_set():
                    transcript_entry["translation_cancelled"] = True
                    self.emit("transcript_update", transcript_entry.copy())
                    continue
                transcript_entry["translated_text"] = translated_text
                transcript_entry["english_text"] = translated_text
                self.emit("target", translated_text)
                self.emit("english", translated_text)
                self.emit("transcript_update", transcript_entry.copy())
                print(f"Target: {translated_text}")
                print("-" * 50)

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
                if transcript_entry is not None:
                    transcript_entry["translation_pending"] = False
                    transcript_entry["translation_error"] = str(exc)
                    self.emit("transcript_update", transcript_entry.copy())
                hint = " (set OFFLINE_ONLY=0 to allow first-time model download)" if self.offline_only else ""
                self.emit("error", f"{exc}{hint}")
                print(f"\nProcessing error: {exc}{hint}")

        pipeline = getattr(self, "conversation_pipeline", None)
        if pipeline is not None:
            pipeline.cancel() if self._stop_event.is_set() else pipeline.flush()

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
        router = getattr(self, "translation_router", None)
        if router is not None:
            terms = self.glossary.translations()
            keep = getattr(getattr(self, "conversation", None), "keep_english_terms", True)
            if self.translation_target_language == "en" or (self.translation_target_language == "ar" and keep):
                terms = {term: "" for term in terms}
            elif self.translation_target_language != "ar":
                terms = {}
            else:
                terms = {term: value for term, value in terms.items() if value}
            with generation_scope(self._stop_event):
                result = router.translate(source_text, self.whisper_language, self.translation_target_language,
                                          context=self._one_way_context[-2:], glossary=terms)
            self._one_way_context.append((source_text, result.text))
            self._one_way_context[:] = self._one_way_context[-2:]
            return result.text
        return self._translate_text_local(source_text)

    def _translate_text_local(self, source_text):
        tokenizer = getattr(self.translator, "tokenizer", None)
        tokens = len(tokenizer.encode(source_text)) if tokenizer else max(1, len(source_text.split()) * 2)
        kwargs = {"max_new_tokens": max(32, min(512, tokens * 3)), "truncation": True,
                  "num_beams": 4, "do_sample": False}
        stopping_criteria = self._generation_stopping_criteria()
        if stopping_criteria is not None:
            kwargs["stopping_criteria"] = stopping_criteria
        with generation_scope(getattr(self, "_stop_event", None)):
            translation = self.translator(source_text, **kwargs)
        return translation[0]["translation_text"]

    def start_background(self, enable_keyboard_shortcuts=False):
        if self.running:
            return
        self._stop_event.clear()
        self.running = True
        save_runtime_config(
            CONFIG_FILE,
            mic_noise_gate=self.mic_noise_gate,
            last_mode=self.mode,
            chunk_duration=self.chunk_duration,
        )
        if self.speech_player:
            self.speech_player.start()
        if getattr(self, "live_pipeline", None):
            self.live_pipeline.start()
        if enable_keyboard_shortcuts and self.interactive:
            self.setup_keyboard_shortcuts()
        self._capture_thread = threading.Thread(target=self.capture_audio, daemon=True)
        self._process_thread = threading.Thread(target=self.process_audio, daemon=True)
        self._capture_thread.start()
        self._process_thread.start()

    def stop_background(self):
        self.running = False
        self._stop_event.set()
        if getattr(self, "live_pipeline", None):
            self.live_pipeline.stop()
        while True:
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
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

    @audio_com_context()
    def save_transcript(self):
        if not self.transcripts:
            print("No transcripts to save.")
            return None

        try:
            transcript_dir = os.fspath(self.transcript_folder)
            os.makedirs(transcript_dir, exist_ok=True)
            timestamp = self.session_start_time.strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(transcript_dir, f"transcript_{timestamp}.txt")
            suffix = 0
            while True:
                try:
                    handle = open(filepath, "x", encoding="utf-8")
                    break
                except FileExistsError:
                    suffix += 1
                    filepath = os.path.join(transcript_dir, f"transcript_{timestamp}_{suffix:03d}.txt")

            with handle:
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
                    source_language = entry.get("language_tag", entry.get("source_language", "source"))
                    target_language = entry.get("target_language", "target")
                    handle.write(f"[{index:03d}] {entry_time}\n")
                    handle.write("-" * 40 + "\n")
                    if entry.get("engine"):
                        handle.write(f"Mode: {entry.get('mode', self.mode)}\nEngine: {entry['engine']}\n")
                    handle.write(f"Source ({source_language}): {source_text}\n")
                    if entry.get("pass_through") and not entry.get("secondary_translation"):
                        handle.write("Target: (same as source)\n\n")
                    else:
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
