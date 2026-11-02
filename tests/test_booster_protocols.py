import base64
import json
from types import SimpleNamespace

import pytest

from engines.provider import AuthenticationError, ProviderError, ProviderQuotaError
from tools.eval.streaming_protocols import ElevenLabsProtocol, SonioxProtocol, SpeechmaticsProtocol


def test_soniox_header_auth_pcm_and_two_way_configuration():
    protocol = SonioxProtocol(terms=["deployment", "API"])
    assert protocol.headers(SimpleNamespace(get=lambda _: "fake-key")) == {"Authorization": "Bearer fake-key"}
    config = protocol.start()
    assert "fake-key" not in json.dumps(config) + protocol.endpoint
    assert config["model"] == "stt-rt-v5" and config["sample_rate"] == 16000
    assert config["translation"] == {"type": "two_way", "language_a": "en", "language_b": "ar"}
    assert config["context"]["translation_terms"][0] == {"source": "deployment", "target": "deployment"}
    assert protocol.finish(1) == "" and protocol.audio(b"\x00\x00") == b"\x00\x00"
    assert SonioxProtocol(two_way=False, target="ar").start()["translation"] == {"type": "one_way", "target_language": "ar"}


def test_synthetic_soniox_tokens_preserve_mixed_source_and_separate_translation():
    update = SonioxProtocol().parse({"tokens": [
        {"text": "بخلص ", "is_final": True, "translation_status": "original", "language": "ar", "start_ms": 100, "end_ms": 700},
        {"text": "deployment", "is_final": True, "translation_status": "original", "language": "en", "start_ms": 700, "end_ms": 900},
        {"text": "<end>", "is_final": True},
        {"text": "I will finish deployment", "is_final": False, "translation_status": "translation", "language": "en"}]})
    assert update.endpoint and len(update.pieces) == 3
    assert "".join(p.text for p in update.pieces if not p.translated) == "بخلص deployment"
    assert update.pieces[0].start_s == .1 and update.pieces[2].end_s is None
    assert update.pieces[2].translated and not update.pieces[2].final
    assert SonioxProtocol().parse({"tokens": [], "finished": True}).done


@pytest.mark.parametrize("model,language", [("enhanced", "ar_en"), ("melia-1", "multi")])
def test_speechmatics_verified_bilingual_models_have_distinct_endpointing(model, language):
    protocol = SpeechmaticsProtocol(model=model, region="eu", terms=["API"])
    config = protocol.start()["transcription_config"]
    assert config["model"] == model and config["language"] == language
    assert ("conversation_config" in config) == (model == "enhanced")
    assert protocol.endpoint == "wss://eu.rt.speechmatics.com/v2/"
    assert protocol.parse({"message": "RecognitionStarted"}).ready
    assert protocol.finish(7) == {"message": "EndOfStream", "last_seq_no": 7}
    assert protocol.parse({"message": "EndOfTranscript"}).done


def test_speechmatics_partial_cannot_be_mistaken_for_final():
    protocol = SpeechmaticsProtocol()
    data = {"metadata": {"transcript": "نراجع API", "start_time": .1, "end_time": 1.2}}
    assert not protocol.parse({"message": "AddPartialTranscript", **data}).pieces[0].final
    assert protocol.parse({"message": "AddTranscript", **data}).pieces[0].final


def test_elevenlabs_encoded_audio_explicit_premium_and_no_duplicate_timestamp_text():
    protocol = ElevenLabsProtocol()
    assert "keyterms=" not in protocol.endpoint and "token=" not in protocol.endpoint
    assert protocol.start() is None and protocol.wait_for_ready
    assert base64.b64decode(protocol.audio(b"\x00\x00")["audio_base_64"]) == b"\x00\x00"
    assert protocol.finish(1)["commit"]
    assert protocol.parse({"message_type": "session_started"}).ready
    assert protocol.parse({"message_type": "committed_transcript", "text": "نراجع API"}).pieces[0].final
    assert not protocol.parse({"message_type": "committed_transcript_with_timestamps", "text": "نراجع API"}).pieces
    with pytest.raises(ValueError, match="premium"):
        ElevenLabsProtocol(terms=["API"])
    assert "keyterms=API" in ElevenLabsProtocol(terms=["API"], allow_keyterm_premium=True).endpoint


@pytest.mark.parametrize("protocol,message,error", [
    (SonioxProtocol(), {"error_code": 401, "error_message": "PRIVATE-INPUT-KEY"}, AuthenticationError),
    (SpeechmaticsProtocol(), {"message": "Error", "type": "quota_exceeded", "reason": "PRIVATE-INPUT-KEY"}, ProviderQuotaError),
    (ElevenLabsProtocol(), {"message_type": "input_error", "error": "PRIVATE-INPUT-KEY"}, ProviderError)])
def test_errors_are_static_and_never_echo_service_payloads(protocol, message, error):
    with pytest.raises(error) as caught:
        protocol.parse(message)
    assert "PRIVATE" not in str(caught.value)
