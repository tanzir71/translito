import threading


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
        if not offline_only:
            _download_repo_with_progress(whisper_model, "Whisper", 0.0, 0.5, on_event)
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
