import os
from pathlib import Path
import threading


FAST_WHISPER_MODELS = {
    "openai/whisper-tiny": "tiny",
    "openai/whisper-base": "base",
    "openai/whisper-small": "small",
    "openai/whisper-medium": "medium",
    "openai/whisper-large-v3": "large-v3",
}


def _local_fast_whisper_model(model_size):
    configured = os.environ.get("TRANSLITO_WHISPER_MODEL_DIR", "").strip()
    if configured:
        folder = Path(configured).expanduser()
    else:
        app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
        folder = app_data / "Translito" / "models" / f"whisper-{model_size}-ct2"
    if all((folder / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
        return str(folder)
    return None


class FastWhisperASR:
    """Use the same selected Whisper weights with efficient CPU inference."""

    def __init__(self, model):
        self.model = model

    def transcribe(self, audio, language, stop_event=None):
        segments, _ = self.model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=3,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        text = []
        for segment in segments:
            if stop_event is not None and stop_event.is_set():
                break
            text.append(segment.text.strip())
        return " ".join(part for part in text if part).strip()


class LoadedModels:
    def __init__(self, key, asr, translator):
        self.key = key
        self.asr = asr
        self.translator = translator


class ModelLoadManager:
    def __init__(self):
        self._condition = threading.Condition()
        self._loaded = None
        self._loading_key = None
        self._loading_error = None

    def load_models(
        self,
        whisper_model,
        translation_model,
        torch_device=-1,
        torch_dtype=None,
        offline_only=False,
        on_event=None,
    ):
        key = (whisper_model, translation_model, torch_device, str(torch_dtype), bool(offline_only))
        with self._condition:
            if self._loaded is not None and self._loaded.key == key:
                return self._loaded
            while self._loading_key is not None:
                if self._loading_key == key:
                    self._condition.wait()
                    if self._loaded is not None and self._loaded.key == key:
                        return self._loaded
                    if self._loading_error is not None:
                        raise self._loading_error
                else:
                    self._condition.wait()
            self._loading_key = key
            self._loading_error = None

        try:
            loaded = self._load_uncached(
                whisper_model,
                translation_model,
                torch_device,
                torch_dtype,
                offline_only,
                on_event,
            )
            with self._condition:
                self._loaded = loaded
                self._loading_key = None
                self._condition.notify_all()
            return loaded
        except Exception as exc:
            with self._condition:
                self._loading_error = exc
                self._loading_key = None
                self._condition.notify_all()
            raise

    def preload_async(self, *args, **kwargs):
        thread = threading.Thread(target=self._preload_target, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread

    def _preload_target(self, *args, **kwargs):
        try:
            self.load_models(*args, **kwargs)
        except Exception:
            pass

    def _load_uncached(
        self,
        whisper_model,
        translation_model,
        torch_device,
        torch_dtype,
        offline_only,
        on_event,
    ):
        _emit(on_event, "status", "Loading models")
        fast_model = FAST_WHISPER_MODELS.get(whisper_model) if torch_device == -1 else None
        fast_model_path = _local_fast_whisper_model(fast_model) if fast_model else None
        if not offline_only:
            if fast_model_path is None:
                whisper_repo = f"Systran/faster-whisper-{fast_model}" if fast_model else whisper_model
                _download_repo_with_progress(whisper_repo, "Whisper", 0.0, 0.5, on_event)
            _download_repo_with_progress(translation_model, "translation", 0.5, 0.5, on_event)

        _emit(
            on_event,
            "model_progress",
            {
                "phase": f"Preparing {whisper_model} - first run is slower, cached afterwards",
                "fraction": None,
            },
        )
        from transformers import pipeline

        if fast_model:
            from faster_whisper import WhisperModel

            asr = FastWhisperASR(
                WhisperModel(
                    fast_model_path or fast_model,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=2,
                    local_files_only=offline_only,
                )
            )
        else:
            asr_kwargs = {"model": whisper_model, "device": torch_device}
            if torch_dtype is not None:
                asr_kwargs["torch_dtype"] = torch_dtype
            try:
                asr = pipeline("automatic-speech-recognition", **asr_kwargs)
            except TypeError:
                asr_kwargs.pop("torch_dtype", None)
                asr = pipeline("automatic-speech-recognition", **asr_kwargs)
            try:
                asr.feature_extractor.return_attention_mask = True
            except Exception:
                pass

        _emit(
            on_event,
            "model_progress",
            {"phase": f"Preparing {translation_model}", "fraction": None},
        )
        translator = pipeline("translation", model=translation_model, device=torch_device)
        _emit(on_event, "model_progress", {"phase": "Models ready", "fraction": 1.0})
        return LoadedModels(
            key=(whisper_model, translation_model, torch_device, str(torch_dtype), bool(offline_only)),
            asr=asr,
            translator=translator,
        )


def _download_repo_with_progress(repo_id, label, offset, span, on_event):
    try:
        from huggingface_hub import snapshot_download
        from tqdm.auto import tqdm

        class ProgressTqdm(tqdm):
            def update(self, n=1):
                result = super().update(n)
                if self.total:
                    fraction = min(1.0, max(0.0, float(self.n) / float(self.total)))
                    _emit(
                        on_event,
                        "model_progress",
                        {
                            "phase": f"Downloading {label} - {int(fraction * 100)}%",
                            "fraction": offset + (span * fraction),
                        },
                    )
                return result

        _emit(
            on_event,
            "model_progress",
            {"phase": f"Downloading {label}", "fraction": offset},
        )
        snapshot_download(repo_id=repo_id, tqdm_class=ProgressTqdm)
    except TypeError:
        snapshot_download(repo_id=repo_id)
    except Exception:
        raise


def _emit(on_event, event_type, payload):
    if callable(on_event):
        try:
            on_event(event_type, payload)
        except Exception:
            pass


GLOBAL_MODEL_MANAGER = ModelLoadManager()
