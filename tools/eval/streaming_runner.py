"""Opt-in, evaluation-only streaming transport. Never registered in the app.

Prices aren't inferred from marketing hourly estimates. An owner-approved
policy must attest to an account-verified ceiling for one <=120s session.
That entire ceiling is reserved before connecting and retained afterwards:
the streaming protocols don't provide an authoritative invoice. This is an
evaluation allocation, not a production billing implementation.
"""
import asyncio
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import logging
import os
from pathlib import Path
import ssl
import threading
import time
from types import SimpleNamespace

import numpy as np

from engines.provider import ProviderError, ProviderNetworkError
from engines.usage import Rate, Units, UsageLedger
from tools.eval.streaming_protocols import ElevenLabsProtocol, SonioxProtocol, SpeechmaticsProtocol
from tools.eval.streaming_rows import CascadedRows, SonioxRows


PROFILES = ("soniox", "speechmatics", "speechmatics-melia", "elevenlabs")
SESSION_SECONDS = 120
MAX_CLIP_SECONDS = 90


def protocol_for(profile, target="en"):
    if profile == "soniox":
        # One-way captions let already-target-language speech pass through.
        return SonioxProtocol(target=target, two_way=False)
    if profile in {"speechmatics", "speechmatics-melia"}:
        return SpeechmaticsProtocol(model="enhanced" if profile == "speechmatics" else "melia-1")
    if profile == "elevenlabs":
        return ElevenLabsProtocol()  # No unverified keyterm premium.
    raise ValueError("Unknown streaming evaluation profile")


def positive_money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError()
        return number
    except Exception:
        raise ValueError("Paid evaluation requires explicit positive allocation and caps") from None


@dataclass(frozen=True)
class PaidPolicy:
    run_cap: Decimal
    monthly_cap: Decimal
    ceiling: Decimal
    key_sha256: str

    @classmethod
    def read(cls, path, profile, *, allow_cloud=False, allow_paid=False):
        if not allow_cloud or not allow_paid or os.environ.get("OFFLINE_ONLY", "0").strip() == "1":
            raise ValueError("Paid evaluation requires --allow-cloud, --allow-paid and an online process")
        if path is None:
            raise ValueError("Paid evaluation requires an owner-approved --paid-policy")
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            account = data["accounts"][profile]
            protocol = protocol_for(profile)
            if (data["version"] != 1 or account["model"] != protocol.model
                    or account["ceiling_verified"] is not True):
                raise ValueError()
            fingerprint = account["credential_sha256"]
            if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(c not in "0123456789abcdef" for c in fingerprint)):
                raise ValueError()
            policy = cls(positive_money(data["approved_run_usd"]), positive_money(data["monthly_cap_usd"]),
                         positive_money(account["session_ceiling_usd"]), fingerprint)
            if policy.ceiling > min(policy.run_cap, policy.monthly_cap):
                raise ValueError()
            return policy
        except Exception:
            raise ValueError("Paid policy is missing, unapproved or has no verified session ceiling") from None


class EvaluationBudget:
    def __init__(self, policy, *, monthly_path, run_path):
        if Path(monthly_path).resolve() == Path(run_path).resolve():
            raise ValueError("Monthly and run ledgers must be separate")
        self.policy = policy
        self.monthly, self.run = UsageLedger(monthly_path), UsageLedger(run_path)

    def reserve(self, provider):
        # 120 / 3600 is exactly 1/30; the rate reserves precisely the agreed
        # ceiling. Audio units represent maximum billable session time, not
        # measured audio sent. Actual PCM duration is recorded separately.
        rate = Rate(per_audio_hour=self.policy.ceiling * 30)
        units = Units(audio_seconds=SESSION_SECONDS)
        run = self.run.reserve(provider, units, rate=rate, monthly_cap=self.policy.run_cap,
                               total_monthly_cap=self.policy.run_cap, history_cap=self.policy.run_cap)
        try:
            month = self.monthly.reserve(provider, units, rate=rate, monthly_cap=self.policy.monthly_cap,
                                         total_monthly_cap=self.policy.monthly_cap)
        except BaseException:
            self.run.settle(run, known_not_billed=True, outcome="failed")
            raise
        return run, month

    def settle(self, tokens, outcome):
        # Don't refund on timeout, mid-session quota/auth errors, cancellation,
        # or apparently successful completion: none proves the invoice amount.
        for ledger, token in zip((self.run, self.monthly), tokens):
            ledger.settle(token, outcome=outcome)


def websocket_connection(protocol, headers):
    """Verified Windows TLS; no proxies, redirects, frame logs or reconnect."""
    from native_tls import configure_native_tls
    configure_native_tls()
    from websockets.asyncio.client import connect

    class NoRedirect(connect):
        def process_redirect(self, exc):
            return ProviderNetworkError()

    logger = logging.Logger("translito.eval.private-websocket", level=logging.CRITICAL)
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return NoRedirect(protocol.endpoint, additional_headers=headers, proxy=None,
                      ssl=ssl.create_default_context(), open_timeout=8, close_timeout=2,
                      max_size=2 * 1024 * 1024, max_queue=16, logger=logger)


async def stream_clip(protocol, samples, headers, *, on_update, connector=websocket_connection,
                      stop_event=None, pace=True, drain_seconds=10, force_end_frames=(), telemetry=None):
    """Send 100ms frames in real time, receive concurrently, and never retry.

    ElevenLabs has no EndOfTranscript event. Its EOF drain requires a commit
    after EOF, then bounded quiet time, and is labeled separately in reports.
    """
    ready, done, sent_eof = asyncio.Event(), asyncio.Event(), asyncio.Event()
    state = telemetry if telemetry is not None else {}
    state.update(frames=0, samples_sent=0, first_text_s=None, completion=None)
    started = time.perf_counter()
    if not protocol.wait_for_ready:
        ready.set()

    def cancelled():
        if stop_event is not None and stop_event.is_set():
            raise asyncio.CancelledError()

    async def send(socket, message):
        cancelled()
        if message is not None:
            await socket.send(json.dumps(message, ensure_ascii=False) if isinstance(message, dict) else message)

    async def sender(socket):
        await asyncio.wait_for(ready.wait(), 10)
        origin = time.perf_counter()
        state["audio_origin"] = origin
        for offset in range(0, len(samples), 1600):
            cancelled()
            if done.is_set():
                raise ProviderError()  # A premature server finish truncates the clip.
            block = samples[offset:offset + 1600]
            if pace:
                # A captured frame is available at its end, not its start.
                await asyncio.sleep(max(0, origin + (offset + len(block)) / 16000 - time.perf_counter()))
            pcm = (np.clip(block, -1, 1) * 32767).astype("<i2").tobytes()
            await send(socket, protocol.audio(pcm))
            state["frames"] += 1
            state["samples_sent"] += len(block)
            if state["frames"] in force_end_frames:
                await send(socket, {"message": "ForceEndOfUtterance"})
        if pace:
            await asyncio.sleep(max(0, origin + len(samples) / 16000 - time.perf_counter()))
        # Set before send: a fast server may answer the EOF inside send().
        sent_eof.set()
        await send(socket, protocol.finish(state["frames"]))

    async def receiver(socket):
        committed_after_eof = False
        while not done.is_set():
            cancelled()
            try:
                raw = await asyncio.wait_for(socket.recv(), .1 if not committed_after_eof else 2)
            except TimeoutError:
                if committed_after_eof:
                    state["completion"] = "post-EOF commit and bounded quiet drain"
                    done.set()
                continue
            if not isinstance(raw, str) or len(raw) > 2 * 1024 * 1024:
                raise ProviderError()
            try:
                message = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ProviderError() from None
            update = protocol.parse(message)
            now = time.perf_counter()
            if update.ready:
                ready.set()
            if update.pieces and state["first_text_s"] is None:
                state["first_text_s"] = now - state.get("audio_origin", started)
            await on_update(update, now, state.get("audio_origin"))
            if protocol.name == "elevenlabs" and sent_eof.is_set() and any(p.final for p in update.pieces):
                committed_after_eof = True
            if update.done:
                if not sent_eof.is_set():
                    raise ProviderError()
                state["completion"] = "server end-of-transcript"
                done.set()

    # Leave ten seconds of the allocation for cancellation/socket cleanup.
    async with asyncio.timeout(SESSION_SECONDS - 10):
        async with connector(protocol, headers) as socket:
            await send(socket, protocol.start())
            receiving = asyncio.create_task(receiver(socket))
            sending = asyncio.create_task(sender(socket))
            try:
                # Receive failures must cancel the sender immediately, rather
                # than continuing to upload audio until the sender's EOF.
                finished, _ = await asyncio.wait((sending, receiving), return_when=asyncio.FIRST_COMPLETED)
                for task in finished:
                    task.result()
                await sending
                await asyncio.wait_for(receiving, drain_seconds)
            finally:
                for task in (sending, receiving):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(sending, receiving, return_exceptions=True)
    state["elapsed_s"] = time.perf_counter() - started
    return state


class StreamingRuntime:
    def __init__(self, profile, *, policy, monthly_path, run_path, target="en", credentials=None,
                 translator=None, connector=websocket_connection, allow_cloud_mt=False):
        self.protocol = protocol_for(profile, target)
        self.policy, self.target = policy, target
        self.credentials, self.translator = credentials, translator
        self.budget = EvaluationBudget(policy, monthly_path=monthly_path, run_path=run_path)
        self.connector, self.allow_cloud_mt = connector, allow_cloud_mt

    def evaluate(self, samples, sample_rate):
        setup_started = time.perf_counter()
        if (sample_rate != 16000 or samples.ndim != 1 or not len(samples)
                or len(samples) / sample_rate > MAX_CLIP_SECONDS or not np.isfinite(samples).all()):
            raise ValueError("Streaming evaluation needs finite mono 16kHz audio, at most 90 seconds")
        if os.environ.get("OFFLINE_ONLY", "0").strip() == "1":
            raise ValueError("Paid evaluation is disabled in an Offline process")
        if self.credentials is None:
            from engines.secrets import CredentialStore
            self.credentials = CredentialStore()
        headers = self.protocol.headers(self.credentials)
        key = next(iter(headers.values())).removeprefix("Bearer ")
        if hashlib.sha256(key.encode()).hexdigest() != self.policy.key_sha256:
            raise ValueError("The credential changed; approve and verify the account policy again")
        force_end_frames = set()
        if self.protocol.name == "speechmatics" and self.protocol.model == "melia-1":
            from audio_processing import AudioChunkProcessor, SpeechActivityDetector
            processor = AudioChunkProcessor(input_sample_rate=16000, speech_detector=SpeechActivityDetector())
            for offset in range(0, len(samples), 1600):
                if any(chunk.kind == "audio" for chunk in processor.append(samples[offset:offset + 1600], 16000)):
                    force_end_frames.add(offset // 1600 + 1)
        from engines.glossary import Glossary
        glossary = Glossary(read_only=True)
        if self.protocol.name in {"soniox", "speechmatics"}:
            self.protocol.terms = tuple(term["english"] for term in glossary.terms
                                        if 0 < len(term["english"]) <= 100)[:50]
        translator = self.translator
        if translator is None and self.protocol.name == "soniox":
            # Native MT doesn't require a local MT model or another account.
            translator = SimpleNamespace()
        if translator is None:
            from engines.mt_quality import LocalQualityTranslator
            translator = LocalQualityTranslator(offline_only=True)
            if self.allow_cloud_mt:
                from dataclasses import replace
                from engines.registry import build_session_routers, provider_factories
                from engines.settings import load_engine_settings
                settings = load_engine_settings()
                if settings.profile == "offline":
                    raise ValueError("Offline settings do not authorize cloud MT evaluation")
                # This is the desktop Free MT chain, with its real free-tier
                # ledger, enabled/Test checks and no paid text overage.
                _, translator = build_session_routers(SimpleNamespace(name="unused", requires_network=False),
                    translator, replace(settings, profile="free", monthly_cap=0),
                    factories=[factory for factory in provider_factories() if factory.kind == "mt"])
            else:
                # Cache-only MT warmup happens before the paid connection.
                # A missing local model must not burn a streaming allocation.
                translator.preload("ar" if self.target == "en" else "en", self.target)
            self.translator = translator
        started = time.perf_counter()
        rows = CascadedRows(self.protocol.name, self.target, translator, glossary, threading.Event())
        setup_seconds = time.perf_counter() - setup_started
        tokens = self.budget.reserve(self.protocol.name)
        updates = []
        native = SonioxRows(self.target) if self.protocol.name == "soniox" else None
        queue = None

        async def receive(update, now, origin):
            updates.append({"received_s": now - started, "final_pieces": sum(p.final for p in update.pieces),
                            "annotations": len(update.annotations), "endpoint": update.endpoint, "warning": update.warning})
            if native is not None:
                native.push(update, now, origin)
                return
            for piece in update.annotations:
                rows.annotate(piece, origin)
            if any(not p.final and not p.translated for p in update.pieces):
                queue.put_nowait(("speech", now, None))
            for piece in update.pieces:
                if piece.final and not piece.translated:
                    queue.put_nowait(("feed", piece, origin))

        async def replay():
            nonlocal queue
            queue = asyncio.Queue()  # Retain final text while MT is busy.

            async def consume():
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), .05)
                    except TimeoutError:
                        if native is not None:
                            native.poll(time.perf_counter())
                        else:
                            await asyncio.to_thread(rows.pipeline.poll)
                        continue
                    if item is None:
                        if native is not None:
                            native.flush(time.perf_counter())
                        else:
                            await asyncio.to_thread(rows.pipeline.flush)
                        return
                    kind, value, origin = item
                    if kind == "speech":
                        await asyncio.to_thread(rows.pipeline.notify_speech, value)
                    else:
                        await asyncio.to_thread(rows.feed, value, origin)

            consumer = asyncio.create_task(consume())
            streaming = asyncio.create_task(stream_clip(self.protocol, samples, headers, on_update=receive,
                connector=self.connector, force_end_frames=force_end_frames, telemetry=state))
            try:
                done, _ = await asyncio.wait((streaming, consumer), return_when=asyncio.FIRST_COMPLETED)
                if consumer in done:
                    consumer.result()
                    raise ProviderError()
                result = await streaming
                queue.put_nowait(None)
                await consumer
                return result
            finally:
                for task in (streaming, consumer):
                    if not task.done():
                        rows.pipeline.stop_event.set()
                        task.cancel()
                await asyncio.gather(streaming, consumer, return_exceptions=True)

        state, errors, outcome = {}, [], "completed"
        try:
            state = asyncio.run(replay())
        except (KeyboardInterrupt, asyncio.CancelledError):
            rows.pipeline.stop_event.set()
            outcome = "cancelled"
            raise
        except Exception as exc:
            outcome = exc.category if isinstance(exc, ProviderError) else "network"
            errors.append(exc.public_message if isinstance(exc, ProviderError) else ProviderNetworkError.public_message)
        finally:
            self.budget.settle(tokens, outcome)
        if native is not None:
            native.flush(time.perf_counter())
            rows.entries = native.entries
            ends, expected = [], len(rows.entries)
        else:
            ends, expected = rows.finish_timing(len(samples) / sample_rate)
        return {"entries": rows.entries, "segment_count": len(rows.entries),
                "processing_latencies_s": [], "speech_end_latencies_s": ends if len(ends) == expected else [],
                "observed_speech_end_latencies_s": ends,
                "latency_expected_rows": expected, "latency_measured_rows": len(ends),
                "latency_coverage": len(ends) / expected if expected else None,
                "elapsed_s": time.perf_counter() - started,
                "mt_characters": sum(map(len, rows.mt_calls)), "mt_requests": len(rows.mt_calls),
                "estimated_cost_usd": str(self.policy.ceiling), "cost_status": "full session allocation retained; invoice unavailable",
                "setup_s": setup_seconds,
                "errors": errors + rows.errors, "stream": state, "updates": updates,
                "utterance_tag_metrics": True,
                **({"target_text": native.target_text, "native_target_alignment": "clip only"} if native is not None else {}),
                "latency_method": "Real-time 100ms PCM; desktop MT completion versus vendor final-word timestamps where available"}
