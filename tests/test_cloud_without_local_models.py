"""Exercise the real cloud capture pipeline with local loading forbidden."""
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from audio_processing import AudioChunkResult
from engines.router import Conversation
from engines.settings import EngineSettings, ProviderSettings, credential_signature
from engines.session_state import resolve_plan, readiness
from engines.model_files import Missing


@pytest.mark.parametrize('one_way', [False, True])
def test_capture_translates_and_stops_with_missing_local_models(tmp_path, monkeypatch, one_way):
    import main, audio_processing, engines.registry
    from engines.paid_streaming import PaidStreamingInterpreter
    monkeypatch.setenv('OFFLINE_ONLY', '0')
    monkeypatch.setattr(main.atexit, 'register', lambda *a: None)
    monkeypatch.setattr(main.GLOBAL_MODEL_MANAGER, 'load_models', lambda **kw: pytest.fail('Cloud attempted local model loading'))
    monkeypatch.setattr('engines.asr_local._lid_model', lambda *a: pytest.fail('Cloud attempted local LID loading'))
    monkeypatch.setattr(audio_processing, 'SpeechActivityDetector', lambda: SimpleNamespace(speech_probability=lambda *a: .99))
    pref = ProviderSettings(enabled=True, account_kind='paid', monthly_cap=Decimal(5))
    pref = replace(pref, tested_signature=credential_signature('soniox', 'fake-key', pref))
    settings = EngineSettings(engine_choice='cloud', profile='custom', monthly_cap=Decimal(5),
        default_asr_provider='soniox', default_asr_model='obsolete-model', default_mt_provider='soniox', providers={'soniox':pref})
    plan = resolve_plan(settings, ('ar','en'), inspect=lambda _: Missing())
    assert readiness(plan).can_start and not plan.required_resources
    original = engines.registry.configured_live_interpreter
    class Stream:
        name = 'soniox'
        generation = 1
        def __init__(self, protocol, credentials, update, error, **kw):
            self.protocol, self.update, self.sent = protocol, update, False
        def open_stream(self): pass
        def push_audio(self, audio):
            if not self.sent:
                self.sent = True
                self.update(self.protocol.parse({'tokens':[
                    {'text':'مرحبا.', 'is_final':True, 'language':'ar', 'translation_status':'original', 'end_ms':200},
                    {'text':'Hello.', 'is_final':True, 'language':'en', 'translation_status':'translation'}]}), 1)
            return True
        def close_stream(self): pass
        def finalize(self): pass
    def interpreter(*a, **kw):
        engine = original(*a, **kw, credentials=SimpleNamespace(get=lambda _: 'fake-key'))
        assert isinstance(engine, PaidStreamingInterpreter)
        assert engine.model == 'stt-rt-v6'
        engine.worker_factory = Stream
        return engine
    monkeypatch.setattr(engines.registry, 'configured_live_interpreter', interpreter)
    class Capture:
        name = 'Synthetic capture'
        isloopback = False
        frames = 0
        def recorder(self, samplerate): return self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def record(self, numframes):
            self.frames += 1
            if self.frames == 4: app.running = False
            return np.full(numframes, .25, np.float32)
    class Processor:
        def append(self, samples, rate): return [AudioChunkResult('audio', samples, rate, .25, .25)]
        def flush(self): return []
    monkeypatch.setattr(main.ArabicAudioTranscriber, 'create_audio_processor', lambda *a, **kw: Processor())
    events = []
    conversation = SimpleNamespace(one_way=True, same_language_speech='passthrough') if one_way else Conversation()
    app = main.ArabicAudioTranscriber(selected_device=Capture(), interactive=False, asr_language='ar', target_language='en',
        translation_model=plan.translation_model, engine_settings=settings, session_plan=plan, conversation=conversation,
        on_event=lambda kind, value: events.append((kind,value)))
    assert app.asr is None
    app.live_pipeline.start()
    assert not app.live_pipeline.interpreter.guard.skip_other_languages
    app.running = True
    app.capture_audio()
    app.process_audio()
    assert app.transcripts and app.transcripts[0]['translated_text'] == 'Hello.'
    assert app.transcripts[0]['asr_engine'] == 'soniox'
    assert not any('selected default needs' in str(value) for _,value in events)
    app.stop_background()
    assert app._stop_event.is_set() and not app.live_pipeline.interpreter.guard.active


def test_optional_filter_prepares_after_cloud_start_without_ui_progress(monkeypatch):
    import threading, time, main
    from engines.model_files import Ready
    monkeypatch.setattr('engines.model_files.inspect_model', lambda _: Ready(__import__('pathlib').Path('cached')))
    app = main.ArabicAudioTranscriber.__new__(main.ArabicAudioTranscriber)
    app.cloud_asr, app.whisper_model = True, 'openai/whisper-base'
    app.whisper_language, app.translation_target_language = 'ar', 'en'
    app._stop_event = threading.Event()
    guard = SimpleNamespace(skip_other_languages=False, language_filter_requested=True)
    app.live_pipeline = SimpleNamespace(lid=None, interpreter=SimpleNamespace(guard=guard, lid=None))
    def load(**kw):
        assert kw == {'notify':False}
        app.asr = SimpleNamespace(model=SimpleNamespace())
    app.ensure_local_asr = Mock(side_effect=load)
    app.prepare_optional_cloud_filter()
    end = time.monotonic() + 2
    while app.live_pipeline.lid is None and time.monotonic() < end:
        time.sleep(.01)
    assert app.live_pipeline.lid is app.live_pipeline.interpreter.lid and guard.skip_other_languages
    app.ensure_local_asr.assert_called_once_with(notify=False)
    app._stop_event.set()
