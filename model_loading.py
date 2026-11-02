import os
from pathlib import Path
import threading

from engines.mt_local import LocalOpusPipeline
from engines.asr_codeswitch import CODESWITCH_REPO, prepared_codeswitch_directory, prepare_codeswitch_model


FAST_WHISPER_MODELS = {
    "openai/whisper-tiny": "tiny",
    "openai/whisper-base": "base",
    "openai/whisper-small": "small",
    "openai/whisper-medium": "medium",
    "openai/whisper-large-v3": "large-v3",
    "openai/whisper-large-v3-turbo": "large-v3-turbo",
    CODESWITCH_REPO: CODESWITCH_REPO,
}


def fast_whisper_repo(alias):
    # faster-whisper's turbo weights are not hosted under Systran. Use the
    # upstream map from the pinned package, including future corrected aliases.
    from faster_whisper.utils import _MODELS
    if alias == CODESWITCH_REPO:
        return alias
    if alias not in _MODELS:
        raise ValueError(f"Unsupported faster-whisper model: {alias}")
    return _MODELS[alias]


def physical_cpu_threads():
    import psutil
    return max(2, (psutil.cpu_count(logical=False) or 2) - 1)


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

    def __init__(self, model, beam_size=3):
        self.model = model
        self.beam_size = beam_size

    def transcribe(self, audio, language, stop_event=None, initial_prompt=None, hotwords=None):
        segments, info = self.model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=self.beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
            temperature=(0.0, 0.2, 0.4, 0.6),
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            repetition_penalty=1.1,
            no_repeat_ngram_size=3,
            initial_prompt=initial_prompt,
            hotwords=hotwords,
        )
        text = []
        accepted = []
        for segment in segments:
            if stop_event is not None and stop_event.is_set():
                break
            text.append(segment.text.strip())
            accepted.append(segment)
        value = " ".join(part for part in text if part).strip()
        from engines.lid import latin_ratio, language_tag
        from engines.types import AsrResult
        scores = [s.avg_logprob for s in accepted if getattr(s, "avg_logprob", None) is not None]
        silence = [s.no_speech_prob for s in accepted if getattr(s, "no_speech_prob", None) is not None]
        detected = getattr(info, "language", None) or language
        self.last_result = AsrResult(
            value, detected, getattr(info, "language_probability", None),
            language_tag(value, acoustic_language=detected), latin_ratio(value),
            sum(scores) / len(scores) if scores else None, max(silence) if silence else None,
            len(audio) / 16000, getattr(self, "provider", "faster-whisper"))
        return value


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
        fast_model = FAST_WHISPER_MODELS.get(whisper_model)
        fast_model_path = _local_fast_whisper_model(fast_model) if fast_model else None
        if whisper_model == CODESWITCH_REPO:
            fast_model_path = prepared_codeswitch_directory()
            if fast_model_path is None:
                if offline_only:
                    raise FileNotFoundError("Download the Arabic code-switch fallback before using it offline.")
                fast_model_path = prepare_codeswitch_model(on_event=on_event)
        if not offline_only:
            if fast_model_path is None:
                whisper_repo = fast_whisper_repo(fast_model) if fast_model else whisper_model
                _download_repo_with_progress(whisper_repo, "Whisper", 0.0, 0.5, on_event)
            if not translation_model.startswith("identity:"):
                repos = translation_model.split("|")
                for i, repo in enumerate(repos):
                    _download_repo_with_progress(repo, "translation", 0.5 + i * 0.5 / len(repos),
                                                 0.5 / len(repos), on_event)

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
                    device="cpu" if torch_device == -1 else "cuda",
                    device_index=0 if torch_device == -1 else int(torch_device),
                    compute_type="int8" if torch_device == -1 else "float16",
                    cpu_threads=physical_cpu_threads(),
                    local_files_only=offline_only,
                )
            )
            if whisper_model == CODESWITCH_REPO:
                asr.provider = "arabic-codeswitch-ct2"
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
        translator = LocalOpusPipeline(translation_model, device=torch_device, offline_only=offline_only)
        _emit(on_event, "model_progress", {"phase": "Models ready", "fraction": 1.0})
        return LoadedModels(
            key=(whisper_model, translation_model, torch_device, str(torch_dtype), bool(offline_only)),
            asr=asr,
            translator=translator,
        )


def _download_repo_with_progress(repo_id, label, offset, span, on_event, *, token=False, cache_dir=None,
                                 local_dir=None, allow_patterns=None):
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
        snapshot_download(repo_id=repo_id, tqdm_class=ProgressTqdm, token=token, cache_dir=cache_dir,
                          local_dir=local_dir, allow_patterns=allow_patterns)
    except TypeError:
        snapshot_download(repo_id=repo_id, token=token, cache_dir=cache_dir,
                          local_dir=local_dir, allow_patterns=allow_patterns)
    except Exception:
        raise


def _emit(on_event, event_type, payload):
    if callable(on_event):
        try:
            on_event(event_type, payload)
        except Exception:
            pass


GLOBAL_MODEL_MANAGER = ModelLoadManager()
