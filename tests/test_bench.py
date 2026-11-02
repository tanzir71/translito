"""Hardware-probe contracts with synthetic audio and fake local models."""
import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import numpy as np
import pytest

from tools.eval import bench


class EnergyVAD:
    def speech_probability(self, samples, rate):
        return float(np.max(np.abs(samples)) > .005)

    def contains_speech(self, samples, rate):
        return np.max(np.abs(samples)) > .005


def arguments(tmp_path, samples=None, **options):
    samples = np.full(32000, .2) if samples is None else samples
    with wave.open(str(tmp_path / "clip.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes((samples * 32767).astype("<i2").tobytes())
    return SimpleNamespace(input=tmp_path, manifest=None, recognizers="small-int8", source="ar",
                           allow_downloads=False, cohere_terms_accepted=False, **options)


def test_no_speech_never_loads_a_recognizer_or_passes_its_speed_gate(tmp_path):
    loader = Mock(side_effect=AssertionError("Model loaded for silence"))
    result = bench.benchmark(arguments(tmp_path, np.zeros(16000)), recognizer_loader=loader, detector_factory=EnergyVAD)
    assert result["status"] == "no_speech" and result["live_headroom_ok"] is None
    assert result["asr_speed_gate_passed"] is False and result["segment_count"] == 0
    loader.assert_not_called()


def test_long_audio_uses_desktop_vad_segments_and_retains_each_result(tmp_path):
    lengths = []
    def decode(audio):
        lengths.append(len(audio))
        return SimpleNamespace(text="مرحبا", language="ar")
    loader = Mock(return_value=bench.RecognizerProbe(decode, "asr", {"model": "fake"}))
    result = bench.benchmark(arguments(tmp_path, np.full(31 * 16000, .2)), recognizer_loader=loader, detector_factory=EnergyVAD)
    assert result["status"] == "measured" and len(lengths) >= 3
    assert max(lengths) <= 15 * 16000 and len(result["predictions"]) == len(lengths)
    assert result["inputs"][0]["sha256"] and result["measurement"] == "asr"
    assert result["vad_compute_s"] >= 0 and result["segment_rtf"] >= 0


def test_long_silence_cannot_dilute_a_slow_decoder_into_a_passing_speed_gate(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(bench, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    def decode(audio):
        clock[0] += 2
        return SimpleNamespace(text="مرحبا", language="ar")
    samples = np.concatenate([np.full(16000, .2), np.zeros(10 * 16000)])
    result = bench.benchmark(arguments(tmp_path, samples), detector_factory=EnergyVAD,
        recognizer_loader=lambda *a, **kw: bench.RecognizerProbe(decode, "asr", {}))
    assert result["rtf"] < .7 and result["segment_rtf"] > .7
    assert result["live_headroom_ok"] is False and result["asr_speed_gate_passed"] is False


def test_empty_transcripts_and_lid_results_cannot_pass_the_asr_gate(tmp_path):
    args = arguments(tmp_path)
    for kind, decoded in [("asr", SimpleNamespace(text="", language="ar")),
                          ("lid", SimpleNamespace(language="ar", probability=.9))]:
        result = bench.benchmark(args, detector_factory=EnergyVAD,
            recognizer_loader=lambda *a, **kw: bench.RecognizerProbe(lambda _: decoded, kind, {}))
        assert result["status"] == "measured" and result["asr_speed_gate_passed"] is False
        assert result["measurement"] == kind


def test_direct_cache_only_benchmark_blocks_sockets_and_restores_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_ONLY", "original")
    def loader(*args, **kwargs):
        assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
        with socket.socket() as connection:
            connection.connect(("127.0.0.1", 9))
        pytest.fail("The offline socket guard didn't run")
    result = bench.benchmark(arguments(tmp_path), recognizer_loader=loader, detector_factory=EnergyVAD)
    assert result["status"] == "unavailable" and result["error_type"] == "RuntimeError"
    assert os.environ["OFFLINE_ONLY"] == "original"


def test_unsupported_model_errors_cannot_echo_private_sdk_details(tmp_path):
    def loader(*a, **kw):
        raise AttributeError("PRIVATE Authorization: hf_example_secret")
    result = bench.benchmark(arguments(tmp_path), recognizer_loader=loader, detector_factory=EnergyVAD)
    assert result["status"] == "unavailable" and result["error_type"] == "AttributeError"
    assert "PRIVATE" not in json.dumps(result) and "hf_example_secret" not in json.dumps(result)


def test_failed_later_segment_keeps_earlier_predictions_without_a_partial_speed_pass(tmp_path):
    decode = Mock(side_effect=[SimpleNamespace(text="مرحبا", language="ar"), RuntimeError("PRIVATE-SDK-DETAIL")])
    result = bench.benchmark(arguments(tmp_path, np.full(31 * 16000, .2)), detector_factory=EnergyVAD,
        recognizer_loader=lambda *a, **kw: bench.RecognizerProbe(decode, "asr", {}))
    assert result["status"] == "unavailable" and len(result["predictions"]) == 1
    assert result["predictions"][0]["text"] == "مرحبا" and result["asr_speed_gate_passed"] is False
    assert result["live_headroom_ok"] is None and "rtf" not in result and "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("name,precision", [("cohere-fp32", "float32"), ("cohere-bf16", "bfloat16"), ("cohere-int8", "int8")])
def test_cohere_probe_uses_app_adapter_and_configured_cache_without_reading_keys(name, precision, monkeypatch):
    import audio_processing
    import app_config
    import engines.asr_cohere_local as cohere
    import engines.secrets
    import torch
    recognizer = Mock()
    recognizer.transcribe.return_value = SimpleNamespace(text="Hello", language="en")
    factory = Mock(return_value=recognizer)
    monkeypatch.setattr(cohere, "CohereLocalRecognizer", factory)
    monkeypatch.setattr(app_config, "load_cohere_cache_dir", lambda: "D:/chosen-cohere-cache")
    monkeypatch.setattr(app_config, "write_config", lambda *a, **kw: pytest.fail("Settings changed"))
    monkeypatch.setattr(audio_processing, "SpeechActivityDetector", EnergyVAD)
    monkeypatch.setattr(engines.secrets, "CredentialStore", lambda: pytest.fail("Cache-only Cohere read the Vault"))
    monkeypatch.setattr(torch, "set_num_threads", Mock())
    # Download consent for other models doesn't imply Cohere terms consent.
    probe = bench.load_recognizer(name, True, language="en")
    assert factory.call_args.kwargs["offline_only"] is True
    assert factory.call_args.kwargs["dtype"] == precision
    assert factory.call_args.kwargs["cache_dir"] == "D:/chosen-cohere-cache"
    assert factory.call_args.kwargs["credentials"] is None
    probe(np.ones(16000))
    assert recognizer.transcribe.call_args.kwargs["hint_language"] == "en"
    assert recognizer.transcribe.call_args.args[1] == 16000
    recognizer.load.assert_called_once()


def test_gated_download_needs_both_flags_and_uses_only_the_vault(monkeypatch):
    import audio_processing
    import app_config
    import engines.asr_cohere_local as cohere
    import engines.secrets
    import torch
    store, factory = Mock(), Mock()
    store.get.return_value = "hf_synthetic_read_token"
    monkeypatch.setattr(engines.secrets, "CredentialStore", lambda: store)
    monkeypatch.setattr(cohere, "CohereLocalRecognizer", factory)
    monkeypatch.setattr(app_config, "load_cohere_cache_dir", lambda: None)
    monkeypatch.setattr(audio_processing, "SpeechActivityDetector", EnergyVAD)
    monkeypatch.setattr(torch, "set_num_threads", Mock())
    bench.load_recognizer("cohere-fp32", False, cohere_terms_accepted=True)
    store.get.assert_not_called()
    probe = bench.load_recognizer("cohere-fp32", True, cohere_terms_accepted=True)
    store.get.assert_called_once_with("huggingface")
    options = factory.call_args.kwargs
    assert options["offline_only"] is False
    assert options["credentials"].get("huggingface") == "hf_synthetic_read_token"
    assert "hf_synthetic_read_token" not in json.dumps(probe.info)


def test_missing_gated_read_token_fails_before_model_construction(monkeypatch):
    import engines.asr_cohere_local as cohere
    import engines.secrets
    factory = Mock()
    monkeypatch.setattr(cohere, "CohereLocalRecognizer", factory)
    monkeypatch.setattr(engines.secrets, "CredentialStore", lambda: SimpleNamespace(get=lambda _: None))
    with pytest.raises(cohere.CohereAccessRequired, match="read token"):
        bench.load_recognizer("cohere-fp32", True, cohere_terms_accepted=True)
    factory.assert_not_called()


def test_cohere_thread_policy_is_applied_after_vad_import_and_reports_actual_threads(monkeypatch):
    import audio_processing
    import app_config
    import engines.asr_cohere_local as cohere
    import model_loading
    import torch
    state = {"threads": 6}
    def vad():
        state["threads"] = 1
        return EnergyVAD()
    monkeypatch.setattr(audio_processing, "SpeechActivityDetector", vad)
    monkeypatch.setattr(torch, "set_num_threads", lambda value: state.update(threads=value))
    monkeypatch.setattr(torch, "get_num_threads", lambda: state["threads"])
    monkeypatch.setattr(model_loading, "physical_cpu_threads", lambda: 5)
    monkeypatch.setattr(app_config, "load_cohere_cache_dir", lambda: None)
    recognizer = Mock()
    monkeypatch.setattr(cohere, "CohereLocalRecognizer", Mock(return_value=recognizer))
    probe = bench.load_recognizer("cohere-fp32", False)
    assert state["threads"] == 5 and probe.info["cpu_threads"] == 5


def test_whisper_probe_reuses_app_override_and_hallucination_guards(monkeypatch):
    import faster_whisper
    import model_loading
    model, create = Mock(), Mock()
    model.transcribe.return_value = ([SimpleNamespace(text="Hello", avg_logprob=-.1, no_speech_prob=0,
                                                      compression_ratio=1)], SimpleNamespace(language="en", language_probability=.9))
    create.return_value = model
    monkeypatch.setattr(faster_whisper, "WhisperModel", create)
    monkeypatch.setattr(model_loading, "_local_fast_whisper_model", lambda _: "D:/app-configured-whisper")
    result = bench.load_recognizer("small-int8", False, language="en")(np.ones(16000))
    assert result.text == "Hello" and create.call_args.args[0] == "D:/app-configured-whisper"
    options = model.transcribe.call_args.kwargs
    assert options["beam_size"] == 3 and options["compression_ratio_threshold"] == 2.4
    assert options["repetition_penalty"] == 1.1 and options["no_repeat_ngram_size"] == 3
    assert options["condition_on_previous_text"] is False


def test_cli_passes_model_terms_confirmation_only_to_cohere_workers(tmp_path, monkeypatch):
    from tools.eval import run_eval
    calls = []
    monkeypatch.setattr(run_eval, "metadata", lambda: {"git_commit": "synthetic"})
    def worker(cmd, **kwargs):
        calls.append(cmd)
        output = Path(cmd[cmd.index("--result-file") + 1])
        name = cmd[cmd.index("--recognizers") + 1]
        output.write_text(json.dumps({"recognizer": name, "status": "unavailable", "peak_rss_bytes": 0}))
    monkeypatch.setattr(run_eval.subprocess, "run", worker)
    run_eval.main(["--input", str(tmp_path), "--output", str(tmp_path / "reports"), "--bench",
                   "--recognizers", "cohere-fp32,small-int8", "--allow-downloads", "--cohere-terms-accepted"])
    assert "--cohere-terms-accepted" in calls[0] and "--cohere-terms-accepted" not in calls[1]
    assert all("--allow-cloud" not in cmd for cmd in calls)


def test_cli_unknown_benchmark_name_fails_before_creating_outputs(tmp_path):
    from tools.eval.run_eval import main
    with pytest.raises(ValueError, match="Unknown recognizer"):
        main(["--input", str(tmp_path), "--output", str(tmp_path / "out"), "--bench", "--recognizers", "invalid"])
    assert not (tmp_path / "out").exists()
