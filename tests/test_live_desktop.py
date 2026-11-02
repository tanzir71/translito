from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from audio_processing import AudioChunkResult
from engines.glossary import Glossary
from engines.registry import ProviderFactory, configured_live_interpreter
from engines.router import Conversation
from engines.settings import EngineSettings, ProviderSettings, credential_signature, load_engine_settings
from engines.types import MtResult
from engines.usage import LOCAL_RATE, UsageLedger


@pytest.fixture(autouse=True)
def online_test_environment(monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "0")


def live_preference():
    value = ProviderSettings(enabled=True, account_kind="free", training_consent=True)
    return replace(value, tested_signature=credential_signature("gemini-live", "fake-key", value))


def test_registry_never_opens_live_client_for_free_offline_or_disabled_accounts(tmp_path):
    credentials = SimpleNamespace(get=Mock(return_value="fake-key"))
    options = dict(credentials=credentials, ledger=UsageLedger(tmp_path / "usage.json"))
    preference = live_preference()
    for profile in ("offline", "free", "custom"):
        assert configured_live_interpreter(EngineSettings(profile=profile, providers={"gemini-live": preference}), **options) is None
    assert configured_live_interpreter(EngineSettings(profile="live-preview"), **options) is None
    credentials.get.assert_not_called()
    settings = EngineSettings(profile="live-preview", providers={"gemini-live": preference})
    assert configured_live_interpreter(settings, offline_only=True, **options) is None
    engine = configured_live_interpreter(settings, **options)
    assert engine is not None and engine._thread is None and not engine.ledger.path.exists()
    credentials.get.return_value = "changed key"
    assert configured_live_interpreter(settings, **options) is None


@pytest.mark.parametrize("mode,capture_rate", [("listen", 48000), ("speak", 16000)])
def test_desktop_capture_to_live_row_and_pcm_route_without_duplicate_asr_or_mt(tmp_path, monkeypatch, mode, capture_rate):
    import main
    import engines.registry
    monkeypatch.setenv("OFFLINE_ONLY", "0")
    monkeypatch.setattr(main.atexit, "register", lambda *a: None)
    monkeypatch.setattr(main, "save_runtime_config", lambda *a, **kw: pytest.fail("Unexpected config write"))
    monkeypatch.setattr(main.GLOBAL_MODEL_MANAGER, "load_models", lambda **kw: SimpleNamespace(asr=Mock(), translator=Mock()))
    speaker = Mock()
    monkeypatch.setattr(main, "SpeechOutputPlayer", lambda **kw: speaker)
    recognizer = SimpleNamespace(name="local", requires_network=False,
                                  lid=SimpleNamespace(detect=Mock(return_value=SimpleNamespace(language="en"))), transcribe=Mock())
    translator = SimpleNamespace(name="local", requires_network=False, models={}, supports=lambda *a: True, translate=Mock())
    sent = []
    class Interpreter:
        name = "gemini-live"
        def start(self, pair, target, two_way, callback):
            assert pair == ("en", "ar") and not two_way
            self.callback = callback
        def push_audio(self, audio):
            sent.append(audio)
            source, target, language = ("The API works.", "API يعمل.", "en") if mode == "speak" else ("مرحبا.", "Hello.", "ar")
            self.callback("input_transcription", {"text": source, "language": language, "finished": True, "end_offset": "0.1s"})
            self.callback("output_transcription", {"text": target, "finished": True})
            self.callback("audio", {"pcm": b"\x01\x00" * 2400, "rate": 24000})
            self.callback("turn_complete", None)
            return True
        def stop(self, **kw):
            pass
    monkeypatch.setattr(engines.registry, "configured_live_interpreter", lambda *a, **kw: Interpreter())
    class Capture:
        name = "fixture capture"
        isloopback = mode == "listen"
        def recorder(self, samplerate):
            assert samplerate == capture_rate
            return self
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def record(self, numframes):
            assert numframes == capture_rate // 10
            app.running = False
            return np.full((numframes, 2), .25, np.float32)
    class Processor:
        def append(self, samples, rate):
            return [AudioChunkResult("audio", np.full(1600, .25, np.float32), 16000, .25, .25)]
        def flush(self):
            return []
    monkeypatch.setattr(main.ArabicAudioTranscriber, "create_audio_processor", lambda *a, **kw: Processor())
    app = main.ArabicAudioTranscriber(selected_device=Capture(), interactive=False, mode=mode, conversation=Conversation(),
        recognizer=recognizer, translator_engine=translator, glossary=Glossary(tmp_path / "terms.json", read_only=True),
        engine_settings=EngineSettings(profile="live-preview"))
    app.live_pipeline.start()
    app.running = True
    app.capture_audio()
    app.process_audio()
    assert len(sent) == 1 and sent[0].shape == (1600,)
    assert app.transcripts[0]["engine"] == "gemini-live" and app.transcripts[0]["translated_text"]
    assert not app.transcripts[0]["translation_pending"]
    recognizer.transcribe.assert_not_called()
    translator.translate.assert_not_called()
    assert speaker.play_stream.call_count == int(mode == "speak")


def test_live_setup_uses_public_sample_and_test_fingerprint_without_persisting_key(tmp_path, monkeypatch):
    import engines.setup
    from engines.interp_gemini_live import GeminiLiveInterpreter
    from engines.setup import ProviderSetup
    monkeypatch.setenv("OFFLINE_ONLY", "0")
    path = tmp_path / "config.ini"
    keys = {}
    credentials = SimpleNamespace(get=keys.get, save=lambda name, key: keys.update({name: key}))
    engine = GeminiLiveInterpreter(credentials, ProviderSettings())
    factory = ProviderFactory("gemini-live", "live", lambda *a: SimpleNamespace(engine=engine, rate=LOCAL_RATE),
                               training_required=True)
    def test_public(actual, audio):
        assert actual is engine and len(audio) == 128000
        assert actual.authorized_key() == "fake-key"
        assert not load_engine_settings(path).provider("gemini-live").enabled
        return MtResult("Public sample translated.", "gemini-live")
    monkeypatch.setattr(engines.setup, "_test_live", test_public)
    controller = ProviderSetup(path=path, credentials=credentials, factories=[factory], ledger=UsageLedger(tmp_path / "usage.json"))
    result = controller.test("gemini-live", replace(live_preference(), tested_signature=""), key="fake-key")
    assert result.enabled and load_engine_settings(path).provider("gemini-live").tested_signature
    assert "fake-key" not in path.read_text()
