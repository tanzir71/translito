"""Local bilingual recognizer: pair LID, Cohere Arabic, explicit fallback."""
from dataclasses import replace
from functools import lru_cache

from engines.asr_cohere_local import CohereAccessRequired, CohereLocalRecognizer
from engines.lid import PairLanguageDetector, decode_with_script_check, language_tag, latin_ratio
from engines.postprocess import postprocess
from engines.types import AsrResult


@lru_cache(maxsize=2)
def _lid_model(offline_only):
    from faster_whisper import WhisperModel
    from model_loading import physical_cpu_threads
    return WhisperModel("base", device="cpu", compute_type="int8",
                        cpu_threads=physical_cpu_threads(), local_files_only=offline_only)


@lru_cache(maxsize=2)
def _cohere_model(device):
    return CohereLocalRecognizer(offline_only=True, device=device)


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
        if lid is None:
            self.on_event("model_progress", {"phase": "Preparing per-utterance language detection",
                                               "fraction": None})
            lid = PairLanguageDetector(_lid_model(offline_only), other_language)
        self.lid = lid
        if other_language == "ar":
            self.cohere = cohere or _cohere_model(device)
            self.cohere.on_event = self.on_event
            try:
                self.cohere.load()
                self._cohere_ready = True
            except CohereAccessRequired:
                self._hint_fallback()

    def _hint_fallback(self):
        if not self._fallback_hint:
            self.on_event("hint", "Cohere Arabic needs its one-time model setup. Using Whisper "
                          "as a fallback; Saudi dialect and mixed English terms may be less accurate.")
            self._fallback_hint = True

    def transcribe(self, audio, sample_rate, *, hint_language=None, prompt=None, stop_event=None):
        decision = self.lid.detect(audio)

        def decode(language):
            if self._cohere_ready:
                try:
                    result = self.cohere.transcribe(audio, sample_rate, hint_language=language,
                                                    prompt=prompt, stop_event=stop_event)
                except (CohereAccessRequired, RuntimeError, MemoryError):
                    self._cohere_ready = False
                    self.on_event("hint", "Cohere Arabic could not decode this segment; using local Whisper.")
            if not self._cohere_ready:
                text = self.whisper.transcribe(
                    audio, language=language, stop_event=stop_event,
                    initial_prompt=("بنراجع ال dashboard وال API في ال meeting بكرة"
                                    if language == "ar" else None),
                    hotwords=self.glossary.hotwords() if self.glossary else None,
                )
                result = getattr(self.whisper, "last_result", None) or AsrResult(
                    text, language, decision.probability, language, latin_ratio(text),
                    None, None, len(audio) / sample_rate, "faster-whisper")
            return replace(result, text=postprocess(result.text).text)

        result = decode_with_script_check(decode, decision, self.other_language)
        text, hits = self.glossary.restore_english(result.text) if self.glossary else (result.text, 0)
        result = replace(result, text=text, latin_ratio=latin_ratio(text),
                         language_prob=decision.probability,
                         language_tag=language_tag(text, self.other_language,
                                                   transliteration_hits=hits,
                                                   acoustic_language=decision.language))
        self.on_event("engine", {"asr": result.provider, "fallback": not self._cohere_ready
                                  and self.other_language == "ar"})
        return result
