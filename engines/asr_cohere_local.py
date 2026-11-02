"""On-demand, gated Cohere Arabic recognition behind VAD.

Weights are never bundled. The UI must collect model-terms consent and store
the read token in Credential Manager before enabling a download.
"""
import threading
import time

import numpy as np

from audio_processing import SpeechActivityDetector, resample_audio
from engines.lid import language_tag, latin_ratio
from engines.postprocess import postprocess
from engines.types import AsrResult


MODEL_ID = "CohereLabs/cohere-transcribe-arabic-07-2026"
MODEL_TERMS_URL = f"https://huggingface.co/{MODEL_ID}"


class CohereAccessRequired(RuntimeError):
    pass


def select_language(hint_language, *, margin=None):
    return "en" if hint_language == "en" and (margin is None or margin >= 0.2) else "ar"


class CohereLocalRecognizer:
    name = "cohere-local"
    requires_network = False

    def __init__(self, *, offline_only=True, dtype="float32", device="cpu", cache_dir=None,
                 credentials=None, on_event=None, detector=None, processor=None, model=None):
        if dtype not in {"float32", "bfloat16", "int8"}:
            raise ValueError("Unsupported Cohere inference precision")
        self.offline_only = offline_only
        self.dtype = dtype
        self.device = device
        self.cache_dir = cache_dir
        self.credentials = credentials
        self.on_event = on_event or (lambda *args: None)
        self.detector = detector
        self.processor = processor
        self.model = model
        self.lock = threading.Lock()
        self.last_rtf = None
        self.slow = False

    def load(self):
        if self.model is not None and self.processor is not None:
            return self
        with self.lock:
            if self.model is not None and self.processor is not None:
                return self
            import torch
            from transformers import AutoProcessor, CohereAsrForConditionalGeneration
            token = self.credentials.get("huggingface") if self.credentials else None
            # No implicit HF token-file login. Access is opt-in through our key store.
            kwargs = {"token": token or False, "local_files_only": self.offline_only}
            if self.cache_dir is not None:
                kwargs["cache_dir"] = str(self.cache_dir)
            self.on_event("model_progress", {"phase": "Preparing Cohere Transcribe Arabic",
                                               "fraction": None})
            try:
                if not self.offline_only:
                    from model_loading import _download_repo_with_progress
                    _download_repo_with_progress(MODEL_ID, "Cohere Arabic", 0, 1,
                                                 self.on_event, token=token or False,
                                                 cache_dir=self.cache_dir)
                processor = AutoProcessor.from_pretrained(MODEL_ID, **kwargs)
                precision = torch.bfloat16 if self.dtype == "bfloat16" else torch.float32
                model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_ID, dtype=precision, **kwargs)
                model.to(self.device).eval()
                if self.dtype == "int8":
                    model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
            except Exception:
                # SDK exceptions can contain request headers/URLs. The UI gets
                # only this actionable, key-free message.
                raise CohereAccessRequired(
                    "Cohere Arabic is not ready. Accept its model terms on Hugging Face, "
                    "save a read token, then download the model; Offline needs cached weights.") from None
            self.processor, self.model = processor, model
            self.on_event("model_progress", {"phase": "Cohere Arabic ready", "fraction": 1.0})
        return self

    def transcribe(self, audio, sample_rate, *, hint_language, prompt=None, stop_event=None):
        samples = resample_audio(np.asarray(audio, dtype=np.float32), sample_rate, 16000)
        duration = len(samples) / 16000
        language = select_language(hint_language)

        def empty():
            return AsrResult("", language, None, language, 0.0, None, None, duration, self.name)

        if stop_event is not None and stop_event.is_set():
            return empty()
        if not samples.size or np.max(np.abs(samples)) < 0.000001:
            return empty()
        if self.detector is None:
            self.detector = SpeechActivityDetector()
        if not self.detector.contains_speech(samples, 16000):
            return empty()
        if duration > 15.05:
            raise ValueError("Cohere live recognition requires VAD segments of at most 15 seconds")
        self.load()
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        class Cancelled(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return stop_event is not None and stop_event.is_set()

        started = time.perf_counter()
        with self.lock, torch.inference_mode():
            inputs = self.processor(audio=samples, sampling_rate=16000,
                                    return_tensors="pt", language=language)
            precision = torch.bfloat16 if self.dtype == "bfloat16" else torch.float32
            inputs.to(self.device, dtype=precision)
            outputs = self.model.generate(**inputs, max_new_tokens=max(32, min(256, round(duration * 16))),
                                          stopping_criteria=StoppingCriteriaList([Cancelled()]),
                                          return_dict_in_generate=True, output_scores=True)
            sequences = outputs.sequences
            kwargs = {"skip_special_tokens": True, "language": language}
            if inputs.get("audio_chunk_index") is not None:
                kwargs["audio_chunk_index"] = inputs["audio_chunk_index"]
            decoded = self.processor.decode(sequences, **kwargs)
            text = decoded if isinstance(decoded, str) else " ".join(decoded)
            score = None
            if getattr(outputs, "scores", None):
                try:
                    scores = self.model.compute_transition_scores(sequences, outputs.scores,
                                                                  normalize_logits=True)
                    score = float(scores.mean().item())
                except (AttributeError, TypeError, NotImplementedError):
                    pass
        self.last_rtf = (time.perf_counter() - started) / max(duration, 0.001)
        self.slow = self.last_rtf >= 0.7
        if stop_event is not None and stop_event.is_set():
            return empty()
        cleaned = postprocess(text).text
        return AsrResult(cleaned, language, None, language_tag(cleaned, acoustic_language=language),
                         latin_ratio(cleaned), score, None, duration, self.name)
