from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import numpy as np
import pytest

from app_config import ConversationConfig
from audio_processing import AudioChunkResult
from engines.cost_guard import CostGuard, GateDecision
from engines.glossary import Glossary
from engines.provider import ProviderBinding
from engines.registry import ProviderFactory, configured_live_interpreter
from engines.settings import EngineSettings, ProviderSettings, credential_signature, save_engine_settings, load_engine_settings
from engines.types import AsrResult, MtResult
from engines.usage import Rate, UsageLedger


def test_paid_connection_test_uses_current_budget_and_zero_cap_blocks_before_credentials(tmp_path,monkeypatch):
    import engines.setup as setup
    monkeypatch.setenv("OFFLINE_ONLY","0")
    path = tmp_path/"config.ini"
    save_engine_settings(EngineSettings(monthly_cap=Decimal(5)),path)
    keys = {}
    credentials = SimpleNamespace(get=Mock(side_effect=lambda key:keys.get(key)),save=Mock(side_effect=lambda name,key:keys.update({name:key})))
    engine = SimpleNamespace(name="soniox",settings=None,inspect_audio=None)
    build = Mock(return_value=ProviderBinding(engine,rate=Rate(per_audio_hour=Decimal(".2"))))
    factory = ProviderFactory("soniox","live",build,account_kind="paid")
    preference = ProviderSettings(enabled=True,monthly_cap=Decimal(5),account_kind="paid")
    def public(actual,audio):
        assert actual.settings.monthly_cap == 5 and len(audio) == 128000
        assert actual.inspect_audio(audio,16000).probability == 1
        return MtResult("Public test.","soniox")
    monkeypatch.setattr(setup,"_test_live",public)
    controller = setup.ProviderSetup(path=path,credentials=credentials,factories=[factory],ledger=UsageLedger(tmp_path/"usage.json"))
    assert controller.test("soniox",preference,key="fake-key").enabled
    assert load_engine_settings(path).provider("soniox").tested_signature
    save_engine_settings(replace(load_engine_settings(path),monthly_cap=Decimal(0)),path)
    build.reset_mock(); credentials.get.reset_mock(); credentials.save.reset_mock()
    with pytest.raises(setup.SetupError,match="above \\$0"):
        controller.test("soniox",preference,key="fake-key")
    build.assert_not_called(); credentials.get.assert_not_called(); credentials.save.assert_not_called()


def test_pair_specific_live_provider_and_model_are_resolved_before_any_socket(tmp_path,monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY","0")
    preference = ProviderSettings(enabled=True,monthly_cap=Decimal(5),account_kind="paid")
    preference = replace(preference,tested_signature=credential_signature("elevenlabs","fake-key",preference))
    settings = EngineSettings(engine_choice="cloud",monthly_cap=Decimal(5),default_asr_provider="soniox",
        providers={"elevenlabs":preference},pair_overrides={"es_en":{"asr_provider":"elevenlabs","asr_model":"scribe_v3_live"}})
    engine = configured_live_interpreter(settings,pair=("es","en"),credentials=SimpleNamespace(get=lambda _:"fake-key"),ledger=UsageLedger(tmp_path/"usage.json"))
    assert engine.name == "elevenlabs" and engine.model == "scribe_v3_live" and engine.worker is None


def test_target_language_is_never_sent_and_lid_preroll_is_retained(tmp_path):
    provider = SimpleNamespace(name="paid",open_stream=Mock(),push_audio=Mock(return_value=True),close_stream=Mock(),finalize=Mock())
    decision = [GateDecision(.9,"en")]
    guard = CostGuard(provider,ledger=UsageLedger(tmp_path/"usage.json"),rate=Rate(per_audio_hour=Decimal(".2")),
        monthly_cap=5,total_monthly_cap=5,languages=("es","en"),excluded_languages=("en",),inspect_audio=lambda *a:decision[0])
    frame = np.full(1600,.2,np.float32)
    for _ in range(10): guard.feed(frame)
    provider.open_stream.assert_not_called()
    decision[0] = GateDecision(.9,None)
    guard.feed(frame); guard.feed(frame)
    decision[0] = GateDecision(.9,"es")
    guard.feed(frame)
    assert len(provider.push_audio.call_args.args[0]) == 4800
    guard.stop()


def test_non_english_fixed_pair_uses_same_desktop_live_pipeline(tmp_path,monkeypatch):
    import main, engines.registry
    monkeypatch.setenv("OFFLINE_ONLY","0")
    monkeypatch.setattr(main.atexit,"register",lambda *a:None)
    monkeypatch.setattr(main.GLOBAL_MODEL_MANAGER,"load_models",lambda **kw:SimpleNamespace(asr=Mock(),translator=Mock()))
    class Interpreter:
        name = "soniox"
        def start(self,pair,target,two_way,callback):
            assert pair == ("fr","de") and target == "de"
            self.callback = callback
        def push_audio(self,audio):
            self.callback("input_transcription",dict(text="Bonjour.",language="fr",finished=True))
            self.callback("output_transcription",dict(text="Hallo.",finished=True))
            return True
        def stop(self,**kwargs): pass
    monkeypatch.setattr(engines.registry,"configured_live_interpreter",lambda *a,**kw:Interpreter())
    recognizer = SimpleNamespace(name="local",requires_network=False,transcribe=Mock())
    translator = SimpleNamespace(name="local",requires_network=False,models={},supports=lambda *a:True,translate=Mock())
    app = main.ArabicAudioTranscriber(interactive=False,asr_language="fr",target_language="de",conversation=ConversationConfig(one_way=True),
        recognizer=recognizer,translator_engine=translator,glossary=Glossary(tmp_path/"terms.json",read_only=True),engine_settings=EngineSettings(engine_choice="cloud"))
    app.live_pipeline.start()
    app.live_pipeline.push_capture(np.ones(1600,np.float32)*.2,16000)
    app.live_pipeline.poll()
    assert app.transcripts[0]["source_text"] == "Bonjour." and app.transcripts[0]["translated_text"] == "Hallo."
    recognizer.transcribe.assert_not_called(); translator.translate.assert_not_called()


def test_late_scribe_timing_updates_original_display_time_without_another_translation(tmp_path):
    from engines.paid_streaming import PaidStreamingInterpreter
    from engines.streaming_protocols import ElevenLabsProtocol
    from engines.conversation_pipeline import ConversationPipeline
    from engines.live_pipeline import LiveConversationPipeline
    from engines.router import FixedPair
    clock, entries, events = [101.5], [], []
    engine = PaidStreamingInterpreter(None, ProviderSettings(), provider="elevenlabs", ledger=UsageLedger(tmp_path/"usage.json"))
    engine.pair, engine.target = ("es", "en"), "en"
    engine.guard = SimpleNamespace(speech_end_at=lambda offset,generation:100+offset if 0<=offset<=2 else None)
    fallback = ConversationPipeline(Mock(),Mock(),FixedPair("es","en"),emit=lambda k,v:events.append((k,v)),
        transcripts=entries,stop_event=threading.Event(),clock=lambda:clock[0])
    live = LiveConversationPipeline(fallback,engine,clock=lambda:clock[0])
    engine.emit = lambda k,v:live.events.put((k,v))
    protocol = ElevenLabsProtocol(languages=("es","en"))
    engine._recognizer_update(protocol.parse({"message_type":"committed_transcript","text":"Hola."}),1)
    live.poll()
    live._handle("output_transcription",dict(text="Hello.",finished=True,replace=True,utterance_id="1-0"))
    assert entries[0]["delay_s"] is None
    clock[0] = 110
    metadata = protocol.parse({"message_type":"committed_transcript_with_timestamps","text":"Hola.",
        "language_code":"es","words":[dict(text="Hola.",start=.1,end=.8)]})
    engine._recognizer_update(metadata,1)
    engine._recognizer_update(metadata,1)
    live.poll()
    assert entries[0]["target_shown_at"] == 101.5
    assert entries[0]["delay_s"] == pytest.approx(.7)
    assert len(entries) == 1 and engine._mt_queue.qsize() == 1
    fallback.translator.translate.assert_not_called()


def test_target_pass_through_uses_local_recognition_and_target_hint_only():
    from engines.asr_local import LocalOneWayRecognizer
    from engines.conversation_pipeline import ConversationPipeline
    from engines.live_pipeline import LiveConversationPipeline
    from engines.router import FixedPair, RecognizerRouter
    decoder = Mock(return_value="Hallo.")
    local = LocalOneWayRecognizer(decoder,"fr",accepts_language_hint=True)
    network = Mock(name="cloud"); network.requires_network = True
    recognizer = RecognizerRouter([ProviderBinding(network),ProviderBinding.local(local)])
    translator, events, entries = Mock(), [], []
    fallback = ConversationPipeline(recognizer,translator,FixedPair("fr","de"),emit=lambda k,v:events.append((k,v)),
        transcripts=entries,stop_event=threading.Event())
    interpreter = SimpleNamespace(gates_target_language=True)
    live = LiveConversationPipeline(fallback,interpreter,lid=SimpleNamespace(detect_any=lambda a:SimpleNamespace(language="de")))
    audio = np.ones(16000,np.float32)*.2
    live.feed(AudioChunkResult("audio",audio,16000,.2,.2))
    assert decoder.call_args.kwargs["hint_language"] == "de"
    assert entries[0]["source_text"] == "Hallo." and entries[0]["not_sent"]
    assert not entries[0]["mt_called"]
    translator.translate.assert_not_called(); network.transcribe.assert_not_called()
    assert fallback.conversation == FixedPair("fr","de") and fallback.variety == ""


def test_budget_edits_update_active_routers_and_zero_cap_stops_the_live_policy(tmp_path):
    from engine_ui import apply_budget
    from engines.live_pipeline import LiveConversationPipeline
    from engines.router import ProviderRouter
    ledger = UsageLedger(tmp_path/"usage.json")
    events = []
    router = ProviderRouter([],total_monthly_cap=5)
    guard = SimpleNamespace(total_monthly_cap=5,fallback_on_budget="local",ledger=ledger,paused=False)
    interpreter = SimpleNamespace(guard=guard,emit=lambda k,v:events.append((k,v)))
    fallback = SimpleNamespace(recognizer=router,translator=router)
    pipeline = SimpleNamespace(fallback=fallback,interpreter=interpreter)
    variable = lambda value:SimpleNamespace(get=lambda:value)
    app = SimpleNamespace(preview_mode=False,_initializing=False,transcriber=SimpleNamespace(conversation_pipeline=pipeline),
        monthly_budget_var=variable(""),budget_fallback_var=variable("stop"),budget_warning_var=variable("75"))
    apply_budget(app)
    assert router.total_monthly_cap == guard.total_monthly_cap == 0
    assert guard.paused and events == [("budget",dict(action="stop",message="Monthly budget reached."))]
    stop = threading.Event()
    live = LiveConversationPipeline.__new__(LiveConversationPipeline)
    live.live, live.emit, live.stop_event = True, Mock(), stop
    live._handle(*events[0])
    assert stop.is_set()


def test_free_choice_never_builds_a_paid_text_provider_even_with_a_positive_budget():
    from engines.registry import build_session_routers
    build = Mock()
    factory = ProviderFactory("gemini","mt",build)
    preference = ProviderSettings(enabled=True,account_kind="paid",monthly_cap=Decimal(5),tested_signature="a"*64)
    settings = EngineSettings(engine_choice="free",monthly_cap=Decimal(5),providers={"gemini":preference})
    local = SimpleNamespace(name="local",requires_network=False)
    _, translator = build_session_routers(local,local,settings,factories=[factory],pair=("es","en"))
    assert [p.name for p in translator.providers] == ["local"]
    build.assert_not_called()


def test_local_translation_model_default_selects_opus_before_available_gemma():
    from engines.mt_quality import LocalQualityTranslator
    from engines.registry import build_session_routers
    opus, gemma = Mock(), Mock()
    opus.translate.return_value = MtResult("Hello.","opus-mt")
    translator = LocalQualityTranslator(opus=opus,gemma=gemma)
    settings = EngineSettings(default_mt_provider="local",default_mt_model="opus")
    local = SimpleNamespace(name="local",requires_network=False)
    _, routed = build_session_routers(local,translator,settings,factories=[],pair=("es","en"))
    assert routed.translate("Hola.","es","en",context=[],glossary={}).text == "Hello."
    assert translator.model == "opus"
    gemma.translate.assert_not_called()
