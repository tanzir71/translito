"""Local bilingual recognizer: pair LID, Cohere Arabic, explicit fallback."""
from dataclasses import replace
from functools import lru_cache

from engines.asr_cohere_local import CohereAccessRequired, CohereLocalRecognizer
from engines.lid import PairLanguageDetector, decode_with_script_check, language_tag, latin_ratio
from engines.postprocess import postprocess
from engines.types import AsrResult
from engines.provider import ProviderError
from engines.cancellation import generation_scope, check_cancelled


@lru_cache(maxsize=2)
def _lid_model(offline_only):
    from faster_whisper import WhisperModel
    from model_loading import physical_cpu_threads
    return WhisperModel("base", device="cpu", compute_type="int8",
                        cpu_threads=physical_cpu_threads(), local_files_only=offline_only)


@lru_cache(maxsize=2)
def _cohere_model(device, cache_dir):
    return CohereLocalRecognizer(offline_only=True, device=device, cache_dir=cache_dir)


def get_cohere_model(*, device="cpu", cache_dir=None, on_event=None):
    if cache_dir is None:
        from app_config import load_cohere_cache_dir
        cache_dir = load_cohere_cache_dir()
    model = _cohere_model(device, str(cache_dir) if cache_dir else None)
    if on_event is not None:
        model.on_event = on_event
    return model


class LocalOneWayRecognizer:
    """Keep the legacy decoder behind the same provider and cancellation gates."""
    name = "local-whisper"
    requires_network = False

    def __init__(self, decode, language, *, glossary=None):
        self.decode, self.language, self.glossary = decode, language, glossary

    def transcribe(self, audio, sample_rate, *, hint_language=None, prompt=None, stop_event=None):
        with generation_scope(stop_event):
            check_cancelled()
            text = self.decode(audio)
            check_cancelled()
            if self.language == "ar" and self.glossary:
                text = self.glossary.restore_english(text)[0]
            return AsrResult(text, self.language, None, self.language, latin_ratio(text),
                             None, None, len(audio) / sample_rate, self.name)


class LocalConversationRecognizer:
    name = "local"
    requires_network = False

    def __init__(self, whisper, *, other_language="ar", offline_only=True, glossary=None,
                 on_event=None, lid=None, cohere=None, device="cpu"):
        self.whisper = whisper
        self.other_language = other_language
        self.glossary = glossary
        self.on_event = on_event or (lambda *args: None)
        self.cohere = cohere
        self._cohere_ready = False
        self._fallback_hint = False
        self._fallback_checked = False
        self.device = device
        if lid is None:
            self.on_event("model_progress", {"phase": "Preparing per-utterance language detection",
                                               "fraction": None})
            lid = PairLanguageDetector(_lid_model(offline_only), other_language)
        self.lid = lid
        if other_language == "ar":
            self.cohere = cohere or get_cohere_model(device=device, on_event=self.on_event)
            self.cohere.on_event = self.on_event
            try:
                self.cohere.load()
                self._cohere_ready = True
            except CohereAccessRequired:
                self._prepare_fallback()

    def _prepare_fallback(self):
        if self._fallback_checked:
            return
        self._fallback_checked = True
        if getattr(self.whisper, "provider", None) == "arabic-codeswitch-ct2":
            return
        try:
            from engines.asr_codeswitch import load_cached_codeswitch
            fallback = load_cached_codeswitch(device=self.device)
            if hasattr(self.whisper, "beam_size"):
                fallback.beam_size = self.whisper.beam_size
            self.whisper = fallback
        except (FileNotFoundError, ValueError, RuntimeError):
            pass

    def _hint_fallback(self):
        if not self._fallback_hint:
            self.on_event("hint", "Using local Whisper as a fallback; Saudi dialect and mixed English terms "
                          "may be less accurate. Set up Cohere Arabic or enable a tested free cloud recognizer in Settings.")
            self._fallback_hint = True

    @property
    def fallback_active(self):
        return self.other_language == "ar" and not self._cohere_ready

    def reset(self):
        self.lid.previous = None

    def transcribe(self, audio, sample_rate, *, hint_language=None, prompt=None, stop_event=None):
        decision = self.lid.detect(audio)
        result = decode_with_script_check(lambda language: self.decode_once(
            audio, sample_rate, language, prompt=prompt, stop_event=stop_event), decision, self.other_language)
        result = self.decorate(result, decision)
        self.on_event("engine", {"asr": result.provider, "fallback": self.fallback_active})
        return result

    def decode_once(self, audio, sample_rate, language, *, prompt=None, stop_event=None,
                    use_cohere=True, allow_whisper=True):
        with generation_scope(stop_event):
            check_cancelled()
            if use_cohere and self._cohere_ready:
                try:
                    result = self.cohere.transcribe(audio, sample_rate, hint_language=language,
                                                    prompt=prompt, stop_event=stop_event)
                    return replace(result, text=postprocess(result.text).text)
                except (CohereAccessRequired, RuntimeError, MemoryError):
                    check_cancelled()
                    self._cohere_ready = False
                    self._prepare_fallback()
            if not allow_whisper:
                raise ProviderError()
            if self.other_language == "ar":
                self._hint_fallback()
            options = dict(language=language, stop_event=stop_event,
                           initial_prompt="بنراجع ال dashboard وال API في ال meeting بكرة" if language == "ar" else None,
                           hotwords=self.glossary.hotwords() if self.glossary else None)
            if callable(getattr(type(self.whisper), "transcribe_result", None)):
                result = self.whisper.transcribe_result(audio, **options)
            else:
                text = self.whisper.transcribe(audio, **options)
                result = getattr(self.whisper, "last_result", None) or AsrResult(
                    text, language, None, language, latin_ratio(text),
                    None, None, len(audio) / sample_rate, "faster-whisper")
            return replace(result, text=postprocess(result.text).text)

    def decorate(self, result, decision):
        result = replace(result, text=postprocess(result.text).text)
        text, hits = self.glossary.restore_english(result.text) if self.glossary else (result.text, 0)
        return replace(result, text=text, latin_ratio=latin_ratio(text),
                         language_prob=decision.probability,
                         language_tag=language_tag(text, self.other_language,
                                                   transliteration_hits=hits,
                                                   acoustic_language=decision.language))


class LocalCohereCandidate:
    name = "cohere-local"
    requires_network = False
    languages = {"en", "ar"}

    def __init__(self, local):
        self.local = local

    def ready(self):
        return self.local._cohere_ready and getattr(self.local.cohere, "slow", False) is not True

    def transcribe(self, audio, sample_rate, *, hint_language, prompt=None, stop_event=None):
        return self.local.decode_once(audio, sample_rate, hint_language, prompt=prompt,
                                       stop_event=stop_event, allow_whisper=False)


class LocalWhisperCandidate:
    name = "local-whisper"
    requires_network = False
    languages = None

    def __init__(self, local):
        self.local = local

    @property
    def fallback_active(self):
        return self.local.other_language == "ar"

    def transcribe(self, audio, sample_rate, *, hint_language, prompt=None, stop_event=None):
        return self.local.decode_once(audio, sample_rate, hint_language, prompt=prompt,
                                       stop_event=stop_event, use_cohere=False)


class RoutedConversationRecognizer:
    """One pair-LID pass and one shared cleanup around all ASR candidates."""
    name = "bilingual-router"

    def __init__(self, local, router):
        self.local, self.router = local, router

    @property
    def requires_network(self):
        return self.router.requires_network

    def reset(self):
        self.local.reset()

    def transcribe(self, audio, sample_rate, *, hint_language=None, prompt=None, stop_event=None):
        with generation_scope(stop_event):
            check_cancelled()
            decision = self.local.lid.detect(audio)
            prompt = prompt or (self.local.glossary.hotwords() if self.local.glossary else None)
            def decode(language):
                return self.router.transcribe(audio, sample_rate, hint_language=language,
                                                prompt=prompt, stop_event=stop_event)
            result = decode_with_script_check(decode, decision, self.local.other_language)
            return self.local.decorate(result, decision)
