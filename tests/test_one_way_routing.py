from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import numpy as np
import pytest

import gui
from main import ArabicAudioTranscriber, translation_target_from_model
from engines.cancellation import GenerationCancelled
from engines.mt_local import UnsupportedPairError
from engines.provider import ProviderBinding, ProviderQuotaError
from engines.registry import ProviderFactory
from engines.settings import EngineSettings, ProviderSettings, credential_signature
from engines.types import AsrResult, MtResult
from engines.usage import LOCAL_RATE, UsageLedger


def test_one_way_session_uses_shared_asr_mt_fallback_and_keeps_english_terms(tmp_path, monkeypatch):
    import main
    from engines.glossary import Glossary
    from engines.registry import build_session_routers
    import engines.registry
    monkeypatch.setenv("OFFLINE_ONLY", "0")
    monkeypatch.setattr(main.atexit, "register", lambda *a: None)
    local_asr = SimpleNamespace(transcribe=Mock(return_value="نراجع ربليكا"))
    local_mt = SimpleNamespace(name="local-mt", requires_network=False, models={}, supports=lambda *a: True,
                               translate=Mock(return_value=MtResult("Review replica", "local-mt")))
    monkeypatch.setattr(main.GLOBAL_MODEL_MANAGER, "load_models", lambda **kw:
                        SimpleNamespace(asr=local_asr, translator=Mock(), translator_engine=local_mt))
    cloud_asr = SimpleNamespace(name="groq", requires_network=True,
        transcribe=Mock(return_value=AsrResult("نراجع ربليكا", "ar", .9, "ar", 0, -.2, 0, 1, "groq")))
    cloud_mt = SimpleNamespace(name="azure", requires_network=True, supports=lambda *a: True,
                               translate=Mock(side_effect=ProviderQuotaError()))
    preferences = {}
    for name in ("groq", "azure"):
        preference = ProviderSettings(enabled=True, account_kind="free")
        preferences[name] = replace(preference, tested_signature=credential_signature(name, "fake-key", preference))
    ledger = UsageLedger(tmp_path / "usage.json")
    def routers(*args, **kwargs):
        return build_session_routers(*args, **kwargs, ledger=ledger,
            credentials=SimpleNamespace(get=lambda _: "fake-key"), factories=[
                ProviderFactory("groq", "asr", lambda *a: ProviderBinding(cloud_asr, rate=LOCAL_RATE)),
                ProviderFactory("azure", "mt", lambda *a: ProviderBinding(cloud_mt, rate=LOCAL_RATE))])
    monkeypatch.setattr(engines.registry, "build_session_routers", routers)
    glossary = Glossary(tmp_path / "glossary.json", read_only=True)
    app = ArabicAudioTranscriber(interactive=False, glossary=glossary,
                                  engine_settings=EngineSettings(providers=preferences))
    assert app.recognize_speech_offline(np.zeros(16000, np.float32)) == "نراجع replica"
    assert app.translate_text("نراجع replica") == "Review replica"
    local_asr.transcribe.assert_not_called()
    assert local_mt.translate.call_args.kwargs["glossary"]["replica"] == ""
    assert ledger.snapshot()["providers"]["groq"]["audio_seconds"] == 1
    app._stop_event.set()
    with pytest.raises(GenerationCancelled):
        app.recognize_speech_offline(np.zeros(16000, np.float32))
    assert cloud_asr.transcribe.call_count == 1


def test_missing_local_pair_requires_cloud_availability_and_preserves_target(monkeypatch):
    import engines.mt_translategemma
    monkeypatch.setattr(engines.mt_translategemma, "gemma_available", lambda *a: False)
    monkeypatch.setattr(gui, "resolve_local_mt", Mock(side_effect=UnsupportedPairError("missing")))
    with pytest.raises(UnsupportedPairError):
        gui.translation_model_for("ar", "fa")
    assert gui.translation_model_for("ar", "fa", cloud_available=True) == "cloud:ar:fa"
    assert translation_target_from_model("cloud:ar:fa") == "fa"
