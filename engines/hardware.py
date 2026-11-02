"""Opt-in first-run local speed check; no microphone or meeting data."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import wave

import numpy as np


SPEED_CLIP = Path(__file__).parent / "data" / "speed-check-ar.wav"


def speed_history_path():
    from app_config import CONFIG_FILE
    return CONFIG_FILE.parent / "speed_checks.json"


def record_speed_check(result, path=None):
    path = Path(path) if path else speed_history_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "checks": []}
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise ValueError("The speed-check history is invalid; it was preserved.")
    data["checks"].append(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def run_speed_check(*, allow_download=False, on_event=None, model_factory=None):
    from model_loading import (FastWhisperASR, _local_fast_whisper_model,
                                _download_repo_with_progress, fast_whisper_repo, physical_cpu_threads)
    from faster_whisper import WhisperModel
    model_id = "large-v3-turbo"
    local = _local_fast_whisper_model(model_id)
    if allow_download and local is None:
        _download_repo_with_progress(fast_whisper_repo(model_id), "speed-check model", 0, 1, on_event)
    with wave.open(str(SPEED_CLIP), "rb") as handle:
        if handle.getframerate() != 16000 or handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("The bundled speed-check audio has an unexpected format.")
        audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32) / 32768
    # The check uses the CPU fallback and the same decoding guards as a meeting.
    # Weights are cache-only here; network is allowed only in the explicit
    # download above. This model is not retained in the live model cache.
    model = (model_factory or WhisperModel)(local or model_id, device="cpu", compute_type="int8",
                                             cpu_threads=physical_cpu_threads(), local_files_only=True)
    recognizer = FastWhisperASR(model, beam_size=3)
    began = time.perf_counter()
    recognizer.transcribe(audio, language="ar")
    seconds = time.perf_counter() - began
    duration = len(audio) / 16000
    rtf = seconds / duration
    return {"created_utc": datetime.now(timezone.utc).isoformat(), "model": model_id,
            "device": "cpu", "compute_type": "int8", "threads": physical_cpu_threads(),
            "audio_seconds": duration, "decode_seconds": seconds, "rtf": rtf,
            "recommended_model": "openai/whisper-small" if rtf > .6 else "openai/whisper-large-v3-turbo"}
