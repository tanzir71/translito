"""Synthetic sockets only. These tests make no vendor/account quality claims."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from engines.provider import AuthenticationError
from engines.types import MtResult
from engines.usage import BudgetExceeded, Rate, Units, UsageLedger
from tools.eval.streaming_protocols import ElevenLabsProtocol, SonioxProtocol, SpeechmaticsProtocol
from tools.eval.streaming_runner import (EvaluationBudget, PaidPolicy, StreamingRuntime,
                                         protocol_for, stream_clip, websocket_connection)


KEY = "synthetic-key-not-a-real-credential"
FINGERPRINT = hashlib.sha256(KEY.encode()).hexdigest()


def policy(ceiling="0.01", run="0.03", monthly="0.05"):
    return PaidPolicy(Decimal(run), Decimal(monthly), Decimal(ceiling), FINGERPRINT)


def write_policy(tmp_path, **updates):
    data = {"version": 1, "approved_run_usd": "0.03", "monthly_cap_usd": "0.05", "accounts": {
        "speechmatics": {"model": "enhanced", "session_ceiling_usd": "0.01",
                         "ceiling_verified": True, "credential_sha256": FINGERPRINT}}}
    data.update(updates)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data))
    return path


def test_explicit_paid_and_upload_gates_run_before_opening_a_policy(tmp_path, monkeypatch):
    path = tmp_path / "does-not-exist.json"
    for cloud, paid in [(False, False), (True, False), (False, True)]:
        with pytest.raises(ValueError, match="--allow-cloud"):
            PaidPolicy.read(path, "speechmatics", allow_cloud=cloud, allow_paid=paid)
    monkeypatch.setenv("OFFLINE_ONLY", "1")
    with pytest.raises(ValueError, match="online"):
        PaidPolicy.read(path, "speechmatics", allow_cloud=True, allow_paid=True)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "bad"])
def test_nonpositive_or_nonfinite_allocation_never_authorizes_calls(tmp_path, amount, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    path = write_policy(tmp_path, approved_run_usd=amount)
    with pytest.raises(ValueError, match="unapproved"):
        PaidPolicy.read(path, "speechmatics", allow_cloud=True, allow_paid=True)


def test_verified_ceiling_and_exact_model_are_required(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    path = write_policy(tmp_path)
    assert PaidPolicy.read(path, "speechmatics", allow_cloud=True, allow_paid=True) == policy()
    data = json.loads(path.read_text())
    data["accounts"]["speechmatics"]["ceiling_verified"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        PaidPolicy.read(path, "speechmatics", allow_cloud=True, allow_paid=True)
    assert protocol_for("soniox").start()["translation"] == {"type": "one_way", "target_language": "en"}
    assert protocol_for("speechmatics-melia").model == "melia-1"


def test_full_allocation_is_reserved_across_providers_before_transport(tmp_path):
    budget = EvaluationBudget(policy(run="0.02"), monthly_path=tmp_path / "monthly.json", run_path=tmp_path / "run.json")
    first = budget.reserve("speechmatics")
    budget.settle(first, "network")
    budget.reserve("elevenlabs")
    with pytest.raises(BudgetExceeded):
        budget.reserve("soniox")
    stats = budget.monthly.snapshot()["providers"]
    assert stats["speechmatics"]["estimated_usd"] == "0.01"
    assert stats["speechmatics"]["audio_seconds"] == 120
    assert stats["elevenlabs"]["estimated_usd"] == "0.01"


def test_monthly_rejection_releases_only_the_uncalled_run_reservation(tmp_path):
    budget = EvaluationBudget(policy(monthly="0.01"), monthly_path=tmp_path / "monthly.json", run_path=tmp_path / "run.json")
    budget.reserve("soniox")
    with pytest.raises(BudgetExceeded):
        budget.reserve("elevenlabs")
    run = json.loads((tmp_path / "run.json").read_text())
    assert len(run["reservations"]) == 2
    rejected = list(run["reservations"].values())[-1]
    assert rejected["released"] and rejected["settled"]


def test_run_cap_does_not_reset_when_utc_month_changes(tmp_path):
    current = [datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)]
    ledger = UsageLedger(tmp_path / "run.json", clock=lambda: current[0])
    options = dict(rate=Rate(per_audio_hour=Decimal("0.30")), monthly_cap=Decimal("1"),
                   total_monthly_cap=Decimal("1"), history_cap=Decimal("0.01"))
    ledger.reserve("speechmatics", Units(audio_seconds=120), **options)
    current[0] = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("elevenlabs", Units(audio_seconds=120), **options)


class FakeSocket:
    def __init__(self, protocol, final_events=()):
        self.protocol = protocol
        self.queue = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.final_events = final_events
        if protocol.name == "speechmatics":
            self.queue.put_nowait(json.dumps({"message": "RecognitionStarted"}))
        elif protocol.name == "elevenlabs":
            self.queue.put_nowait(json.dumps({"message_type": "session_started"}))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def recv(self):
        return await self.queue.get()

    async def send(self, message):
        self.sent.append(message)
        data = json.loads(message) if isinstance(message, str) and message else message
        ending = (message == "" or (isinstance(data, dict) and
                  (data.get("message") == "EndOfStream" or data.get("commit") is True)))
        if ending:
            for event in self.final_events:
                await self.queue.put(json.dumps(event))
            if self.protocol.name == "speechmatics":
                await self.queue.put(json.dumps({"message": "EndOfTranscript"}))
            elif self.protocol.name == "soniox":
                await self.queue.put(json.dumps({"tokens": [], "finished": True}))


def test_transport_ready_pcm_frame_count_and_local_vad_force_endpoint():
    protocol = SpeechmaticsProtocol(model="melia-1")
    sockets, seen = [], []

    def connect(p, headers):
        socket = FakeSocket(p, [{"message": "AddTranscript", "metadata": {
            "transcript": "نراجع API.", "start_time": 0, "end_time": .2}}])
        sockets.append(socket)
        return socket

    async def receive(update, *args):
        seen.extend(update.pieces)

    result = asyncio.run(stream_clip(protocol, np.ones(3200, dtype=np.float32), {}, on_update=receive,
                                    connector=connect, pace=False, force_end_frames={2}))
    sent = sockets[0].sent
    assert len([x for x in sent if isinstance(x, bytes)]) == 2
    assert json.loads(sent[-1]) == {"message": "EndOfStream", "last_seq_no": 2}
    assert json.loads(sent[-2]) == {"message": "ForceEndOfUtterance"}
    assert result["samples_sent"] == 3200 and result["completion"] == "server end-of-transcript"
    assert len(seen) == 1 and seen[0].final and sockets[0].closed


def test_receive_error_stops_audio_and_never_reconnects():
    attempts, sockets = [], []

    def connect(p, headers):
        attempts.append(1)
        socket = FakeSocket(p)
        socket.queue = asyncio.Queue()
        socket.queue.put_nowait(json.dumps({"error_code": 401, "error_message": KEY}))
        sockets.append(socket)
        return socket

    async def receive(*args):
        pass

    with pytest.raises(AuthenticationError) as caught:
        asyncio.run(stream_clip(SonioxProtocol(), np.zeros(16000), {}, on_update=receive, connector=connect))
    assert KEY not in str(caught.value) and len(attempts) == 1
    assert len([x for x in sockets[0].sent if isinstance(x, bytes)]) <= 1
    assert sockets[0].closed


def test_no_ready_event_means_no_paid_audio_is_sent():
    async def scenario():
        socket = FakeSocket(SpeechmaticsProtocol())
        socket.queue = asyncio.Queue()
        async def receive(*args):
            pass
        task = asyncio.create_task(stream_clip(SpeechmaticsProtocol(), np.zeros(1600), {}, on_update=receive,
                                               connector=lambda *args: socket))
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(socket.sent) == 1 and not isinstance(socket.sent[0], bytes)
        assert socket.closed
    asyncio.run(scenario())


def runtime(tmp_path, *, profile="speechmatics", credentials=None, connector=None):
    calls = []
    translator = SimpleNamespace(translate=lambda text, *a, **k: (calls.append(text) or MtResult("Check API.", "fake-mt")))
    value = StreamingRuntime(profile, policy=policy(), monthly_path=tmp_path / "monthly.json",
                             run_path=tmp_path / "run.json", translator=translator,
                             credentials=credentials or SimpleNamespace(get=lambda _: KEY),
                             connector=connector or (lambda *a: pytest.fail("Unexpected connection")))
    return value, calls


def test_changed_key_or_invalid_audio_never_creates_ledgers_or_connects(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    value, _ = runtime(tmp_path, credentials=SimpleNamespace(get=lambda _: "changed-key"))
    with pytest.raises(ValueError, match="credential changed"):
        value.evaluate(np.zeros(1600), 16000)
    with pytest.raises(ValueError, match="90 seconds"):
        value.evaluate(np.zeros(90 * 16000 + 1), 16000)
    with pytest.raises(ValueError):
        value.evaluate(np.full(1600, float("nan")), 16000)
    assert not list(tmp_path.iterdir())


def test_midstream_auth_error_retains_full_allocation_and_redacts_payload(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    def connect(p, headers):
        socket = FakeSocket(p)
        socket.queue.put_nowait(json.dumps({"message": "Error", "reason": KEY}))
        return socket
    value, calls = runtime(tmp_path, connector=connect)
    result = value.evaluate(np.zeros(1600), 16000)
    assert result["errors"] and KEY not in json.dumps(result)
    assert result["estimated_cost_usd"] == "0.01" and not calls
    assert result["stream"]["samples_sent"] <= 1600
    assert value.budget.monthly.snapshot()["providers"]["speechmatics"]["estimated_usd"] == "0.01"


def test_actual_desktop_pipeline_passes_english_and_translates_arabic_once(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    def connect(p, headers):
        assert value.budget.monthly.snapshot()["providers"]["speechmatics"]["estimated_usd"] == "0.01"
        return FakeSocket(p, [
            {"message": "AddPartialTranscript", "metadata": {"transcript": "WRONG PARTIAL", "end_time": .02}},
            {"message": "AddTranscript", "metadata": {"transcript": "The API works.", "start_time": 0, "end_time": .03}},
            {"message": "AddTranscript", "metadata": {"transcript": "راجع API.", "start_time": .03, "end_time": .07}}])
    value, calls = runtime(tmp_path, connector=connect)
    result = value.evaluate(np.zeros(1600), 16000)
    assert not result["errors"] and len(result["entries"]) == 2
    assert result["entries"][0]["pass_through"] and not result["entries"][0]["mt_called"]
    assert calls == ["راجع API."] and result["mt_requests"] == 1
    assert result["entries"][1]["translated_text"] == "Check API."
    assert len(result["speech_end_latencies_s"]) == 2


def test_native_soniox_source_and_target_use_only_finals_and_no_extra_mt(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    def connect(p, headers):
        return FakeSocket(p, [{"tokens": [
            {"text": "WRONG", "is_final": False, "language": "ar"},
            {"text": "مرحبا", "is_final": True, "translation_status": "original", "language": "ar"},
            {"text": "Hello", "is_final": True, "translation_status": "translation", "language": "en"},
            {"text": " API", "is_final": True, "translation_status": "none", "language": "en"}]}])
    value, calls = runtime(tmp_path, profile="soniox", connector=connect)
    result = value.evaluate(np.zeros(1600), 16000)
    assert result["entries"][0]["source_text"] == "مرحبا API"
    assert result["entries"][0]["translated_text"] == ""  # No invented per-row translation pairing.
    assert result["target_text"] == "Hello API" and result["entries"][0]["language_tag"] == "mix"
    assert not calls and result["utterance_tag_metrics"] and not result["speech_end_latencies_s"]


def test_elevenlabs_late_timestamp_event_cannot_double_mt(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    def connect(p, headers):
        return FakeSocket(p, [
            {"message_type": "committed_transcript", "text": "راجع API."},
            {"message_type": "committed_transcript_with_timestamps", "text": "راجع API.",
             "language_code": "ar", "words": [{"text": "API", "start": .01, "end": .09}]}])
    value, calls = runtime(tmp_path, profile="elevenlabs", connector=connect)
    result = value.evaluate(np.zeros(1600), 16000)
    assert not result["errors"] and len(calls) == 1 and result["mt_requests"] == 1
    assert result["stream"]["completion"] == "post-EOF commit and bounded quiet drain"
    assert len(result["speech_end_latencies_s"]) == 1 and result["latency_coverage"] == 1
    assert result["entries"][0]["vendor_languages"] == ["ar"]


def test_native_soniox_does_not_load_a_local_mt_model(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    def connect(p, headers):
        return FakeSocket(p)
    value, _ = runtime(tmp_path, profile="soniox", connector=connect)
    value.translator = None
    monkeypatch.setattr("engines.mt_quality.LocalQualityTranslator",
                        lambda **kwargs: pytest.fail("Native MT must not load a local model"))
    assert not value.evaluate(np.zeros(1600), 16000)["errors"]


def test_p0_report_uses_retained_paid_allocation_instead_of_local_zero(tmp_path, monkeypatch):
    from tools.eval import run_eval
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"synthetic-audio-placeholder")
    monkeypatch.setattr(run_eval, "read_audio", lambda _: (np.zeros(1600), 16000))
    result = {"entries": [{"source_text": "hello", "translated_text": "hello", "pass_through": True}],
              "processing_latencies_s": [], "speech_end_latencies_s": [], "segment_count": 1,
              "elapsed_s": .1, "mt_characters": 0, "mt_requests": 0, "errors": [],
              "estimated_cost_usd": "0.01", "cost_status": "allocation retained", "utterance_tag_metrics": False}
    monkeypatch.setattr(run_eval, "StreamingRuntime", lambda *a, **kw: SimpleNamespace(evaluate=lambda *args: result))
    args = SimpleNamespace(source="ar", target="en", paid_policy=write_policy(tmp_path), allow_cloud=True,
                           allow_paid=True, paid_usage=tmp_path / "month.json", paid_run_usage=tmp_path / "run.json",
                           stream_mt="offline")
    report = run_eval.evaluate_profile([{"path": clip, "source": "hello", "target": "hello", "tags": ["en"], "terms": {}}],
                                       "speechmatics", args)
    assert report["rows"][0]["estimated_cost_usd"] == "0.01"
    assert report["rows"][0]["cost_status"] == "allocation retained"
    assert report["rows"][0]["tag_accuracy"] is None


def test_websocket_options_prevent_redirect_proxy_and_private_debug_logs(monkeypatch):
    import websockets.asyncio.client
    created = {}
    class FakeConnect:
        def __init__(self, endpoint, **kwargs):
            created.update(endpoint=endpoint, **kwargs)
    monkeypatch.setattr(websockets.asyncio.client, "connect", FakeConnect)
    connection = websocket_connection(ElevenLabsProtocol(), {"xi-api-key": KEY})
    assert created["proxy"] is None and created["ssl"].check_hostname
    assert created["logger"].propagate is False and created["logger"].level >= 50
    assert KEY not in created["endpoint"]
    assert isinstance(connection.process_redirect(RuntimeError(KEY)), Exception)


def test_cli_paid_profile_fails_before_output_or_worker_creation(tmp_path, monkeypatch):
    from tools.eval.run_eval import main
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    with pytest.raises(ValueError, match="--allow-cloud"):
        main(["--input", str(tmp_path), "--profiles", "soniox", "--output", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()


def test_unpunctuated_final_translates_during_socket_silence_before_eof(tmp_path, monkeypatch):
    from tools.eval import streaming_runner
    from engines.sentence_assembler import SentenceAssembler
    from tools.eval.streaming_rows import CascadedRows
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    monkeypatch.setattr(streaming_runner, "CascadedRows", lambda *a, **kw: CascadedRows(
        *a, **kw, assembler=SentenceAssembler(idle_seconds=.01, clock=time.perf_counter)))
    translated = threading.Event()
    class Socket(FakeSocket):
        async def send(self, message):
            await super().send(message)
            audio_count = len([m for m in self.sent if isinstance(m, bytes)])
            if isinstance(message, bytes) and audio_count == 1:
                await self.queue.put(json.dumps({"message": "AddTranscript", "metadata": {
                    "transcript": "نراجع API", "start_time": 0, "end_time": .05}}))
            if isinstance(message, bytes) and audio_count == 2:
                assert await asyncio.to_thread(translated.wait, 2), "MT waited for EOF instead of the idle timer"
    value, _ = runtime(tmp_path, connector=lambda p, h: Socket(p))
    calls = []
    def translate(text, *args, **kwargs):
        calls.append(text)
        translated.set()
        return MtResult("Check API.", "fake")
    value.translator = SimpleNamespace(translate=translate)
    result = value.evaluate(np.zeros(4800), 16000)
    assert not result["errors"] and translated.is_set() and calls == ["نراجع API"]


def test_busy_mt_does_not_block_receiving_its_delayed_timestamp(tmp_path, monkeypatch):
    from tools.eval import streaming_runner
    from tools.eval.streaming_rows import CascadedRows
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    started, annotated = threading.Event(), threading.Event()
    class Rows(CascadedRows):
        def annotate(self, *args):
            super().annotate(*args)
            annotated.set()
    monkeypatch.setattr(streaming_runner, "CascadedRows", Rows)
    class Socket(FakeSocket):
        async def send(self, message):
            if isinstance(message, str) and json.loads(message).get("commit"):
                self.sent.append(message)
                await self.queue.put(json.dumps({"message_type": "committed_transcript", "text": "راجع API."}))
                assert await asyncio.to_thread(started.wait, 2)
                await self.queue.put(json.dumps({"message_type": "committed_transcript_with_timestamps",
                    "text": "راجع API.", "language_code": "ar", "words": [{"start": 0, "end": .08}]}))
            else:
                await super().send(message)
    value, _ = runtime(tmp_path, profile="elevenlabs", connector=lambda p, h: Socket(p))
    received_while_busy = []
    def translate(*args, **kwargs):
        started.set()
        received_while_busy.append(annotated.wait(2))
        return MtResult("Check API.", "fake")
    value.translator = SimpleNamespace(translate=translate)
    result = value.evaluate(np.zeros(1600), 16000)
    assert not result["errors"] and received_while_busy == [True]
    assert result["latency_coverage"] == 1


def test_missing_timestamp_on_one_row_withholds_primary_latency_for_the_clip(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)
    def connect(p, headers):
        return FakeSocket(p, [
            {"message_type": "committed_transcript", "text": "Hello."},
            {"message_type": "committed_transcript", "text": "راجع API."},
            {"message_type": "committed_transcript_with_timestamps", "text": "Hello.",
             "language_code": "en", "words": [{"start": 0, "end": .05}]}])
    value, _ = runtime(tmp_path, profile="elevenlabs", connector=connect)
    result = value.evaluate(np.zeros(1600), 16000)
    assert not result["errors"] and result["latency_coverage"] == .5
    assert len(result["observed_speech_end_latencies_s"]) == 1 and result["speech_end_latencies_s"] == []


def test_real_time_replay_waits_until_each_frame_has_been_captured():
    samples, telemetry, sent = np.zeros(2400), {}, []
    class Socket(FakeSocket):
        async def send(self, message):
            if isinstance(message, bytes):
                sent.append(time.perf_counter() - telemetry["audio_origin"])
            await super().send(message)
    async def receive(*args):
        pass
    asyncio.run(stream_clip(SpeechmaticsProtocol(), samples, {}, on_update=receive,
                            connector=lambda p, h: Socket(p), telemetry=telemetry))
    assert len(sent) == 2 and sent[0] >= .098 and sent[1] >= .148
