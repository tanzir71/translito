"""Local MT preference: cached TranslateGemma, then verified Marian models."""
from engines.cancellation import GenerationCancelled, check_cancelled
from engines.mt_local import OpusTranslator, UnsupportedPairError
from engines.mt_translategemma import (LocalTranslationUnavailable, cached_translator,
                                       configured_model_path)


class LocalQualityTranslator:
    name = "local"
    requires_network = False

    def __init__(self, *, offline_only=True, device=-1, on_hint=None, opus=None, gemma=None):
        self.opus = opus or OpusTranslator(offline_only=offline_only, device=device, on_hint=on_hint)
        self.gemma = gemma or cached_translator(str(configured_model_path()))
        self.on_hint = on_hint or (lambda text: None)
        self._fallback_shown = False

    @property
    def models(self):
        return self.opus.models

    def supports(self, source, target):
        return self.gemma.supports(source, target) or self.opus.supports(source, target)

    def _hint_fallback(self):
        if not self._fallback_shown:
            self.on_hint("TranslateGemma could not translate this line. Using the local Lite translator.")
            self._fallback_shown = True

    def preload(self, source, target):
        if self.gemma.supports(source, target):
            try:
                return self.gemma.warmup()
            except (LocalTranslationUnavailable, OSError, RuntimeError, ValueError):
                self._hint_fallback()
        return self.opus.preload(source, target)

    def translate(self, text, source, target, *, context, glossary):
        check_cancelled()
        if self.gemma.supports(source, target):
            try:
                return self.gemma.translate(text, source, target, context=context, glossary=glossary)
            except GenerationCancelled:
                raise
            except (LocalTranslationUnavailable, OSError, RuntimeError, ValueError):
                self._hint_fallback()
        check_cancelled()
        if not self.opus.supports(source, target):
            raise UnsupportedPairError("This pair needs a working TranslateGemma model or a cloud translator.")
        return self.opus.translate(text, source, target, context=context, glossary=glossary)


class BoundLocalTranslator:
    """Compatibility with the one-way callable pipeline API."""
    tokenizer = None

    def __init__(self, engine, source, target):
        self.engine, self.source, self.target = engine, source, target

    def __call__(self, text, **kwargs):
        result = self.engine.translate(text, self.source, self.target, context=[], glossary={})
        return [{"translation_text": result.text}]
