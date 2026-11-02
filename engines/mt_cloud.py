"""Shared text/span preparation. No credentials, requests or retry policy here."""
from engines.cancellation import check_cancelled
from engines.protect import apply_preferred_terms, protect, unescape_translation
from engines.provider import ProviderError
from engines.types import MtResult
from engines.usage import Units


LANGUAGES = frozenset({"en", "ar", "fr", "de", "es", "it", "pt", "ru", "tr", "fa", "ur"})


class MarkupTranslator:
    requires_network = True
    languages = LANGUAGES
    adapter = None

    def supports(self, source, target):
        return source in self.languages and target in self.languages

    def prepare(self, text, source, target, glossary):
        text = apply_preferred_terms(text, glossary) if source == "en" else text
        return protect(text, self.adapter, latin=target == "en", other_script=source == "en",
                       terms=[term for term, value in glossary.items() if not value])

    def estimate_usage(self, text, source, target, *, context, glossary):
        # Include markup as a conservative character ceiling before sending.
        return Units(characters=len(self.markup(self.prepare(text, source, target, glossary).text)))

    def markup(self, text):
        return "<div>" + text + "</div>"

    def translate(self, text, source, target, *, context, glossary):
        check_cancelled()
        if source == target or not text.strip():
            return MtResult(text, self.name)
        if not self.supports(source, target):
            raise ProviderError()
        protected = self.prepare(text, source, target, glossary)
        output = self.request(self.markup(protected.text), source, target, context=context, glossary=glossary)
        check_cancelled()
        if not isinstance(output, str):
            raise ProviderError()
        output = unescape_translation(output).strip()
        if not output or not protected.verify(output):
            raise ProviderError()
        return MtResult(output, self.name)
