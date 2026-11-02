"""Bilingual routing policy, independent of local/cloud provider selection."""
from dataclasses import dataclass
from decimal import Decimal
import time

from engines.cancellation import GenerationCancelled, check_cancelled
from engines.provider import ProviderError
from engines.usage import (BudgetExceeded, QuotaExceeded, Units, UsageLedger, UsageUnavailable)


@dataclass(frozen=True)
class Conversation:
    other_language: str = "ar"
    my_language: str = "en"
    audience_language: str = "ar"
    show_both: bool = False
    keep_english_terms: bool = True
    same_language_speech: str = "passthrough"  # passthrough | voice | mute

    def __post_init__(self):
        if self.other_language == "en" or self.my_language not in {"en", self.other_language}:
            raise ValueError("Conversation must contain English plus one other language")
        if self.audience_language not in {"en", self.other_language}:
            raise ValueError("Audience language must be in the conversation pair")
        if self.same_language_speech not in {"passthrough", "voice", "mute"}:
            raise ValueError("Unknown same-language speech action")


@dataclass(frozen=True)
class Route:
    source: str
    target: str
    translate: bool
    speech: str  # none | passthrough | voice | mute
    protect_latin: bool = False
    protect_other_script: bool = False
    protect_glossary: bool = False
    secondary_target: str | None = None


def route_utterance(tag, mode, conversation):
    other = conversation.other_language
    if tag not in {"en", other, "mix"}:
        raise ValueError(f"Utterance language {tag!r} is outside the conversation pair")
    if mode not in {"listen", "speak"}:
        raise ValueError("Unknown conversation mode")
    output = conversation.my_language if mode == "listen" else conversation.audience_language
    source = "en" if tag == "en" else other
    if mode == "speak" and (tag == output or (tag == "mix" and output == other)):
        return Route(source, output, False, conversation.same_language_speech)
    if tag == output:
        return Route(source, output, False, "none", secondary_target=(
            other if output == "en" else "en") if conversation.show_both else None)
    return Route(
        "en" if tag == "mix" and output == other else source,
        output, True, "voice" if mode == "speak" else "none",
        protect_latin=tag == "mix" and output == "en",
        protect_other_script=tag == "mix" and output == other,
        protect_glossary=output == other and conversation.keep_english_terms,
    )


def translate_utterance(result, mode, conversation, translator, *, context=None, glossary=None):
    """The pass-through branch intentionally never calls a translator."""
    route = route_utterance(result.language_tag, mode, conversation)
    if not route.translate:
        return result.text, route
    translated = translator.translate(result.text, route.source, route.target,
                                      context=context or [], glossary=glossary or {})
    return translated.text, route


class ProviderRouter:
    """Ordered fallback with no network call before key and budget checks."""
    def __init__(self, providers, *, offline_only=False, ledger=None,
                 total_monthly_cap=Decimal("0"), on_event=None, clock=time.monotonic):
        self.providers = list(providers)
        self.offline_only = offline_only
        self.ledger = ledger if ledger is not None else UsageLedger()
        self.total_monthly_cap = total_monthly_cap
        self.emit = on_event or (lambda *args: None)
        self.clock = clock
        self.hinted = set()
        self.cooldown = {}
        self.accounting_failed = False

    def _hint(self, provider, reason, text):
        key = (provider, reason)
        if key not in self.hinted:
            self.hinted.add(key)
            self.emit("hint", f"{provider}: {text}")

    def _settle(self, reservation, **kwargs):
        if reservation is None:
            return
        try:
            self.ledger.settle(reservation, **kwargs)
        except (UsageUnavailable, OSError, ValueError):
            self.accounting_failed = True
            self._hint("Usage", "write", "Usage could not be updated. Further cloud requests are paused; local processing continues.")

    def _invoke(self, operation, units, args, kwargs, *, supports=None):
        failed = False
        for provider in self.providers:
            check_cancelled()
            if not provider.enabled:
                continue
            if provider.network:
                if self.offline_only:
                    continue
                if self.accounting_failed:
                    failed = True
                    continue
                if not provider.tested:
                    self._hint(provider.name, "untested", "Test this provider's key in Settings before enabling it.")
                    failed = True
                    continue
                if self.cooldown.get(provider.name, 0) > self.clock():
                    failed = True
                    continue
                try:
                    ready = provider.ready()
                except Exception:
                    ready = False
                if not ready:
                    self._hint(provider.name, "key", "The tested key is unavailable or has changed. Test it again in Settings.")
                    failed = True
                    continue
            if supports is not None and not supports(provider.engine):
                continue
            reservation = None
            try:
                if provider.network:
                    if provider.rate is None:
                        raise BudgetExceeded("This provider's pricing policy is not configured.")
                    estimate = getattr(provider.engine, "estimate_usage", None)
                    quantity = estimate(*args, **kwargs) if callable(estimate) else units
                    reservation = self.ledger.reserve(
                        provider.name, quantity, rate=provider.rate, allowance=provider.allowance,
                        quota=provider.quota, monthly_cap=provider.monthly_cap,
                        total_monthly_cap=self.total_monthly_cap)
                check_cancelled()
                result = getattr(provider.engine, operation)(*args, **kwargs)
                self._settle(reservation)
                check_cancelled()
                self.emit("engine", {"mt" if operation == "translate" else "asr": result.provider,
                                       "stage": "mt" if operation == "translate" else "asr",
                                       "fallback": failed or bool(getattr(provider.engine, "fallback_active", False))})
                return result
            except GenerationCancelled:
                self._settle(reservation, outcome="cancelled")
                raise
            except (BudgetExceeded, QuotaExceeded) as exc:
                self._hint(provider.name, type(exc).__name__, str(exc) + " Using the next available engine.")
            except (UsageUnavailable, OSError) as exc:
                self._settle(reservation, outcome="network")
                self._hint(provider.name, "unavailable", "The provider or usage file is unavailable. Using the next available engine.")
            except ProviderError as exc:
                self._settle(reservation, known_not_billed=exc.known_not_billed, outcome=exc.category)
                self.cooldown[provider.name] = self.clock() + (300 if exc.category == "auth" else 60)
                self._hint(provider.name, exc.category, exc.public_message + " Using the next available engine.")
            except Exception:
                # SDK exceptions may include headers, keys or input text.
                # Only the typed, static error above is safe to show verbatim.
                self._settle(reservation, outcome="failed")
                self.cooldown[provider.name] = self.clock() + 60
                self._hint(provider.name, "failed", "The request failed. Using the next available engine.")
            failed = True
        raise ProviderError() from None


class TranslatorRouter(ProviderRouter):
    name = "translation-router"

    @property
    def requires_network(self):
        return not self.offline_only and any(p.network and p.enabled for p in self.providers)

    def supports(self, source, target):
        return any(p.enabled and (not p.network or (not self.offline_only and p.tested))
                   and p.engine.supports(source, target) for p in self.providers)

    def translate(self, text, source, target, *, context, glossary):
        if source == target or not text.strip():
            from engines.types import MtResult
            return MtResult(text, "pass-through")
        return self._invoke("translate", Units(characters=len(text)), (text, source, target),
                            {"context": context, "glossary": glossary},
                            supports=lambda engine: engine.supports(source, target))


class RecognizerRouter(ProviderRouter):
    name = "recognition-router"

    @property
    def requires_network(self):
        return not self.offline_only and any(p.network and p.enabled for p in self.providers)

    def reset(self):
        for binding in self.providers:
            reset = getattr(binding.engine, "reset", None)
            if callable(reset):
                reset()

    def transcribe(self, audio, sample_rate, *, hint_language=None, prompt=None, stop_event=None):
        from engines.cancellation import generation_scope
        with generation_scope(stop_event):
            return self._invoke("transcribe", Units(audio_seconds=len(audio) / sample_rate),
                                (audio, sample_rate), {"hint_language": hint_language,
                                "prompt": prompt, "stop_event": stop_event})
