"""Explicitly enabled, free-tier-only Live Translate worker.

The transport callback carries transient input/output text and PCM, never SDK
errors or credentials. The desktop controller owns rows and Speak/Listen policy.
"""
import asyncio
import logging
import os
import queue
import threading

import numpy as np

from engines.cloud_http import provider_key
from engines.provider import AuthenticationError, ProviderBinding, ProviderError, ProviderNetworkError, ProviderQuotaError
from engines.settings import credential_signature
from engines.usage import LOCAL_RATE, Units, UsageLedger


MODEL = "gemini-3.5-live-translate-preview"
SAMPLE_RATE, FRAME_SAMPLES = 16000, 1600


class _ReconnectRequested(Exception):
    pass


def connect_config(target, handle=None, *, resume=True):
    from google.genai import types
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"], input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        translation_config=types.TranslationConfig(target_language_code=target, echo_target_language=False))
    if resume:
        config.session_resumption = types.SessionResumptionConfig(handle=handle)
    return config


def _client(key):
    from google import genai
    from google.genai import types
    from native_tls import configure_native_tls
    configure_native_tls()
    # The WebSocket library's DEBUG wire log includes authentication headers
    # and private PCM/text. Keep it off even when the app enables debug logs.
    logging.getLogger("websockets.client").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    # No ADC, environment API key or paid Vertex fallback. Retry is owned here.
    return genai.Client(api_key=key, vertexai=False,
                        http_options=types.HttpOptions(timeout=10000, retry_options=types.HttpRetryOptions(attempts=1)))


class GeminiLiveInterpreter:
    name = "gemini-live"
    requires_network = True
    model = MODEL

    def __init__(self, credentials, preference, *, ledger=None, client_factory=_client, reconnect_delay=.5):
        self.credentials, self.preference = credentials, preference
        self.ledger = ledger if ledger is not None else UsageLedger()
        self.client_factory, self.reconnect_delay = client_factory, reconnect_delay
        self._lock = threading.RLock()
        self._thread = self._loop = self._task = None
        self._stopped = threading.Event()
        self._stopped.set()
        self.failed = False
        self.emit = lambda *a: None

    def authorized_key(self):
        if os.environ.get("OFFLINE_ONLY", "0").strip() == "1":
            raise ProviderNetworkError()
        preference = self.preference
        if (not preference.enabled or not preference.tested_signature or preference.account_kind != "free"
                or not preference.training_consent or preference.monthly_cap != 0):
            raise AuthenticationError()
        key = provider_key(self.credentials, self.name)
        if credential_signature(self.name, key, preference) != preference.tested_signature:
            raise AuthenticationError()
        return key

    def start(self, conversation, output_language, two_way, on_event):
        if len(conversation) != 2 or "en" not in conversation or output_language not in conversation:
            raise ValueError("Choose English plus one other language and an output in that pair")
        if two_way:
            raise ValueError("Gemini Live Translate preview supports one-way output only")
        # Check before creating a thread, ledger or client.
        self.authorized_key()
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("The previous interpreter worker is still stopping")
            self.emit = on_event
            self.target = output_language
            self.frames, self._tail, self._pending = queue.Queue(), np.empty(0, np.float32), None
            self._stopped = threading.Event()
            self.failed, self.resume_handle, self.resume_supported = False, None, True
            self._reservation, self._sent_samples, self._connection_requests = None, 0, 1
            self._thread = threading.Thread(target=self._worker, daemon=True, name="Translito Live Translate")
            self._thread.start()

    def push_audio(self, pcm16k_mono_f32):
        samples = np.asarray(pcm16k_mono_f32, dtype=np.float32)
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise ValueError("Live input must be finite mono float audio at 16 kHz")
        with self._lock:
            if self._stopped.is_set() or self.failed:
                return False
            samples = np.concatenate((self._tail, samples))
            end = len(samples) // FRAME_SAMPLES * FRAME_SAMPLES
            for offset in range(0, end, FRAME_SAMPLES):
                self.frames.put((np.clip(samples[offset:offset + FRAME_SAMPLES], -1, 1) * 32767).astype("<i2").tobytes())
            self._tail = samples[end:].copy()
            return True

    def stop(self, timeout=3):
        with self._lock:
            self._stopped.set()
            if self._loop and self._task:
                try:
                    self._loop.call_soon_threadsafe(self._task.cancel)
                except RuntimeError:
                    pass
            worker = self._thread
        if worker and worker is not threading.current_thread():
            worker.join(timeout=timeout)

    def _event(self, kind, payload=None):
        if not self._stopped.is_set():
            self.emit(kind, payload)

    def _worker(self):
        try:
            asyncio.run(self._run())
        except Exception:
            # Errors from SDKs may contain headers and private audio/text.
            self.failed = True
            self._event("fallback", "Live translation stopped. Continuing with the Free profile.")
        finally:
            self._stopped.set()

    def _reserve(self, samples):
        if self._reservation and self._sent_samples + samples <= SAMPLE_RATE * 30:
            return
        self._settle()
        self.authorized_key()
        self._reservation = self.ledger.reserve(self.name, Units(audio_seconds=30, requests=self._connection_requests),
                                                 rate=LOCAL_RATE, monthly_cap=0, total_monthly_cap=0)
        self._sent_samples = 0

    def _settle(self, *, uncertain=False):
        if self._reservation is None:
            return
        token = self._reservation
        if uncertain:
            self.ledger.settle(token, outcome="network")
        else:
            self.ledger.settle(token, actual=Units(audio_seconds=self._sent_samples / SAMPLE_RATE,
                                                  requests=self._connection_requests))
        self._reservation = None
        self._connection_requests = 0

    async def _send(self, session):
        from google.genai import types
        next_frame_at = asyncio.get_running_loop().time()
        while not self._stopped.is_set():
            if os.environ.get("OFFLINE_ONLY", "0").strip() == "1":
                raise ProviderNetworkError()
            if self._pending is None:
                try:
                    self._pending = self.frames.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(.01)
                    continue
            self._reserve(len(self._pending) // 2)
            await asyncio.sleep(max(0, next_frame_at - asyncio.get_running_loop().time()))
            await asyncio.wait_for(session.send_realtime_input(
                audio=types.Blob(data=self._pending, mime_type="audio/pcm;rate=16000")), timeout=5)
            next_frame_at = asyncio.get_running_loop().time() + len(self._pending) / (2 * SAMPLE_RATE)
            self._sent_samples += len(self._pending) // 2
            self._pending = None

    async def _receive(self, session):
        while not self._stopped.is_set():
            received = False
            async for response in session.receive():
                received = True
                if self._stopped.is_set():
                    return
                update = response.session_resumption_update
                if update and update.resumable and update.new_handle:
                    self.resume_handle = update.new_handle
                content = response.server_content
                if content:
                    for name in ("input_transcription", "output_transcription"):
                        transcript = getattr(content, name, None)
                        if transcript and transcript.text:
                            self._failures = 0
                            self._event(name, {"text": transcript.text, "language": transcript.language_code,
                                              "finished": bool(transcript.finished), "start_offset": transcript.start_offset,
                                              "end_offset": transcript.end_offset})
                    if content.model_turn:
                        for part in content.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                if not (part.inline_data.mime_type or "").startswith("audio/pcm"):
                                    raise ProviderError()
                                self._failures = 0
                                self._event("audio", {"pcm": part.inline_data.data, "rate": 24000})
                    if content.interrupted:
                        self._event("interrupted")
                if response.go_away:
                    raise _ReconnectRequested()
            if not received:
                raise ProviderNetworkError()

    async def _run(self):
        self._loop, self._task = asyncio.get_running_loop(), asyncio.current_task()
        self._failures, client = 0, None
        try:
            while not self._stopped.is_set():
                tasks = []
                try:
                    key = self.authorized_key()
                    client = self.client_factory(key)
                    self._event("status", "Connecting to Live Translate" if not self._failures else "Reconnecting…")
                    async with client.aio.live.connect(model=MODEL, config=connect_config(
                            self.target, self.resume_handle, resume=self.resume_supported)) as session:
                        self._connection_requests = 1
                        self._event("connected")
                        tasks = [asyncio.create_task(self._send(session)), asyncio.create_task(self._receive(session))]
                        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            task.result()
                        raise ProviderNetworkError()
                except asyncio.CancelledError:
                    break
                except Exception as error:
                    planned = isinstance(error, _ReconnectRequested)
                    code = getattr(error, "code", None)
                    if code == 400 and self.resume_supported:
                        # Translation-preview capability can differ from the
                        # general Live API. Retry once with a fresh session.
                        self.resume_supported, self.resume_handle = False, None
                    elif not planned:
                        self._failures += 1
                    self._settle(uncertain=self._pending is not None)
                    self._event("reconnecting")
                    if isinstance(error, (AuthenticationError, ProviderQuotaError)) or code in {401, 403, 429} or self._failures >= 3:
                        self.failed = True
                        self._event("fallback", "Live translation is unavailable or its free quota ended. Continuing with the Free profile.")
                        return
                finally:
                    for task in tasks:
                        task.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                    if client:
                        await asyncio.wait_for(client.aio.aclose(), timeout=2)
                        client = None
                if not self._stopped.is_set():
                    await asyncio.sleep(self.reconnect_delay)
        finally:
            try:
                self._settle(uncertain=self._pending is not None)
            finally:
                self._loop = self._task = None


def build(preference, credentials):
    return ProviderBinding(GeminiLiveInterpreter(credentials, preference), rate=LOCAL_RATE
                            if preference.account_kind == "free" and preference.training_consent else None, monthly_cap=0)
