from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from engines.asr_local import LocalConversationRecognizer
from engines.glossary import Glossary
from engines.lid import PairLanguageDetector
from engines.provider import AuthenticationError, ProviderBinding, ProviderQuotaError
from engines.registry import ProviderFactory, build_session_routers
from engines.settings import EngineSettings, ProviderSettings, credential_signature
from engines.types import AsrResult
from engines.usage import LOCAL_RATE, UsageLedger


def recognized(text, name, lang="ar"):
    return AsrResult(text, lang, .9, lang, 0, -.2, 0, 2, name)


def configured(local, tmp_path, *, cohere_error=None, groq_error=None):
    key = "fake-key"
    preferences, factories, engines = {}, [], {}
    for name, kind, error in (("cohere-api", "trial", cohere_error), ("groq", "free", groq_error)):
        pref = ProviderSettings(enabled=True, account_kind=kind)
        preferences[name] = replace(pref, tested_signature=credential_signature(name, key, pref))
        engine = SimpleNamespace(name=name, requires_network=True, languages={"ar", "en"},
                                 transcribe=Mock(side_effect=error, return_value=recognized("راجع ربليكا", name)))
        engines[name] = engine
        factories.append(ProviderFactory(name, "asr", lambda pref, credentials, engine=engine: ProviderBinding(engine, rate=LOCAL_RATE)))
    mt = SimpleNamespace(name="local-mt", requires_network=False)
    router, _ = build_session_routers(local, mt, EngineSettings(providers=preferences), factories=factories,
                                      credentials=SimpleNamespace(get=lambda _: key), ledger=UsageLedger(tmp_path / "usage.json"))
    return router, engines


def local_recognizer(tmp_path, monkeypatch, *, slow=False, fail=False):
    import engines.asr_codeswitch
    monkeypatch.setattr(engines.asr_codeswitch, "load_cached_codeswitch", Mock(side_effect=FileNotFoundError()))
    lid = Mock()
    lid.detect_language.return_value = ("ar", .9, [("ar", .9), ("en", .1)])
    cohere = SimpleNamespace(load=Mock(), slow=slow, transcribe=Mock(
        side_effect=RuntimeError("local error") if fail else None, return_value=recognized("راجع replica", "cohere-local")))
    whisper = SimpleNamespace(last_result=None, transcribe=Mock(return_value="راجع ربليكا"))
    local = LocalConversationRecognizer(whisper, cohere=cohere, lid=PairLanguageDetector(lid),
                                         glossary=Glossary(tmp_path / "terms.json"))
    return local, lid


def test_ready_local_cohere_is_used_before_cloud_and_pair_lid_runs_once(tmp_path, monkeypatch):
    local, lid = local_recognizer(tmp_path, monkeypatch)
    router, engines = configured(local, tmp_path)
    assert router.transcribe(np.ones(32000), 16000).provider == "cohere-local"
    lid.detect_language.assert_called_once()
    for engine in engines.values():
        engine.transcribe.assert_not_called()
    assert not router.router.ledger.path.exists()


def test_slow_local_uses_cohere_api_then_groq_and_shared_back_transliteration(tmp_path, monkeypatch):
    local, lid = local_recognizer(tmp_path, monkeypatch, slow=True)
    router, engines = configured(local, tmp_path, cohere_error=ProviderQuotaError())
    result = router.transcribe(np.ones(32000), 16000)
    assert result.provider == "groq" and result.text == "راجع replica" and result.language_tag == "mix"
    assert engines["cohere-api"].transcribe.call_args.kwargs["hint_language"] == "ar"
    local.cohere.transcribe.assert_not_called()
    local.whisper.transcribe.assert_not_called()
    lid.detect_language.assert_called_once()


def test_local_failure_and_cloud_rejection_retain_same_audio_for_whisper(tmp_path, monkeypatch):
    local, lid = local_recognizer(tmp_path, monkeypatch, fail=True)
    router, _ = configured(local, tmp_path, cohere_error=AuthenticationError(), groq_error=ProviderQuotaError())
    audio = np.ones(32000)
    result = router.transcribe(audio, 16000)
    assert result.provider == "faster-whisper" and result.text == "راجع replica"
    assert local.whisper.transcribe.call_args.args[0] is audio
    lid.detect_language.assert_called_once()
