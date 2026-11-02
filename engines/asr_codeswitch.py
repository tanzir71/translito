"""Prepare the Apache-2.0 CT2 fallback with a verified, local tokenizer."""
import json
import os
from pathlib import Path


CODESWITCH_REPO = "Seif-Eldeen-Sameh/whisper-medium-arabic-codeswitched-ct2"
TOKENIZER_REPO = "Seif-Eldeen-Sameh/whisper-medium-arabic-codeswitched"
REQUIRED = ("model.bin", "config.json", "vocabulary.json", "tokenizer.json")


def codeswitch_directory():
    configured = os.environ.get("TRANSLITO_CODESWITCH_MODEL_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    from app_config import CONFIG_FILE, load_cohere_cache_dir
    cohere = load_cohere_cache_dir()
    root = Path(cohere).parent if cohere else CONFIG_FILE.parent / "models"
    return root / "whisper-arabic-codeswitch-ct2"


def validate_tokenizer(directory):
    directory = Path(directory)
    vocabulary = json.loads((directory / "vocabulary.json").read_text(encoding="utf-8"))
    tokenizer = json.loads((directory / "tokenizer.json").read_text(encoding="utf-8"))
    token_ids = dict(tokenizer["model"]["vocab"])
    token_ids.update({item["content"]: item["id"] for item in tokenizer.get("added_tokens", [])})
    items = vocabulary.items() if isinstance(vocabulary, dict) else ((token, i) for i, token in enumerate(vocabulary))
    if any(token_ids.get(token) != index for token, index in items):
        raise ValueError("The code-switch tokenizer does not match the model vocabulary; files were preserved.")


def prepared_codeswitch_directory(directory=None):
    folder = Path(directory) if directory else codeswitch_directory()
    if not all((folder / name).is_file() for name in REQUIRED):
        return None
    validate_tokenizer(folder)
    return str(folder)


def prepare_codeswitch_model(directory=None, on_event=None):
    from huggingface_hub import hf_hub_download
    from model_loading import _download_repo_with_progress
    folder = Path(directory) if directory else codeswitch_directory()
    folder.mkdir(parents=True, exist_ok=True)
    # Download only inference files, never training checkpoints/optimizer state.
    _download_repo_with_progress(CODESWITCH_REPO, "Arabic code-switch fallback", 0, 0.9,
                                 on_event, local_dir=folder,
                                 allow_patterns=["model.bin", "config.json", "vocabulary.json"])
    hf_hub_download(TOKENIZER_REPO, "tokenizer.json", token=False, local_dir=folder)
    validate_tokenizer(folder)
    if callable(on_event):
        on_event("model_progress", {"phase": "Arabic code-switch fallback ready", "fraction": 1.0})
    return str(folder)


def load_cached_codeswitch(*, device="cpu"):
    from faster_whisper import WhisperModel
    from model_loading import FastWhisperASR, physical_cpu_threads
    folder = prepared_codeswitch_directory()
    if folder is None:
        raise FileNotFoundError("Download the Arabic code-switch fallback before using it offline.")
    recognizer = FastWhisperASR(WhisperModel(folder, device=device.split(":")[0],
        device_index=int(device.split(":")[1]) if ":" in device else 0,
        compute_type="int8" if device == "cpu" else "float16", cpu_threads=physical_cpu_threads(),
        local_files_only=True))
    recognizer.provider = "arabic-codeswitch-ct2"
    return recognizer
