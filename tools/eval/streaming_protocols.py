"""Thin booster wire contracts for evaluation, never registered in the app.

No sockets, credential access, audio capture or paid calls occur on import or
construction. A separately authorized runner must own transport and accounting.
Server examples in the tests are synthetic contract fixtures, not live results.
"""
import base64
from dataclasses import dataclass
import math
from urllib.parse import urlencode

from engines.cloud_http import provider_key
from engines.provider import AuthenticationError, ProviderError, ProviderQuotaError


@dataclass(frozen=True)
class StreamPiece:
    text: str
    final: bool
    translated: bool = False
    language: str | None = None
    speaker: str | None = None
    start_s: float | None = None
    end_s: float | None = None
    translation_status: str | None = None


@dataclass(frozen=True)
class StreamUpdate:
    pieces: tuple[StreamPiece, ...] = ()
    ready: bool = False
    done: bool = False
    endpoint: bool = False
    warning: bool = False
    annotations: tuple[StreamPiece, ...] = ()
    boundaries: tuple[int, ...] = ()  # Soniox source boundaries, in piece order.


def _object(value):
    if not isinstance(value, dict):
        raise ProviderError()
    return value


def _time(value, scale=1):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ProviderError()
    return value / scale


def _text(value):
    if not isinstance(value, str):
        raise ProviderError()
    return value


def _error(code):
    # Never expose a provider's error text, request body or URL in exceptions.
    if code in {401, 403, "auth_error", "unaccepted_terms_error"}:
        raise AuthenticationError()
    if code in {402, 429, "quota_exceeded", "quota_exceeded_error", "rate_limited", "throttled"}:
        raise ProviderQuotaError()
    raise ProviderError()


def _terms(values):
    values = tuple(values)
    if len(values) > 50 or any(not isinstance(term, str) or not term.strip() or len(term) > 100 for term in values):
        raise ValueError("Supply at most 50 nonempty keyterms of at most 100 characters")
    return values


class SonioxProtocol:
    name = "soniox"
    endpoint = "wss://stt-rt.soniox.com/transcribe-websocket"
    model = "stt-rt-v5"
    wait_for_ready = False

    def __init__(self, *, other="ar", target="en", two_way=True, terms=()):
        if other != "ar" or target not in {"en", "ar"}:
            raise ValueError("This evaluation contract is restricted to Saudi Arabic and English")
        self.other, self.target, self.two_way, self.terms = other, target, bool(two_way), _terms(terms)

    def headers(self, credentials):
        return {"Authorization": "Bearer " + provider_key(credentials, self.name)}

    def start(self):
        translation = ({"type": "two_way", "language_a": "en", "language_b": self.other} if self.two_way else
                       {"type": "one_way", "target_language": self.target})
        return {"model": self.model, "audio_format": "pcm_s16le", "sample_rate": 16000, "num_channels": 1,
                "language_hints": ["en", self.other], "language_hints_strict": True,
                "enable_language_identification": True, "enable_speaker_diarization": True,
                "enable_endpoint_detection": True, "translation": translation,
                "context": {"terms": list(self.terms),
                            "translation_terms": [{"source": term, "target": term} for term in self.terms]}}

    def audio(self, pcm):
        return bytes(pcm)

    def finish(self, frame_count):
        return ""  # Empty text ends the stream; empty binary does not.

    def parse(self, message):
        message = _object(message)
        if message.get("error_code") or message.get("error_type"):
            _error(message.get("error_code"))
        tokens = message.get("tokens", [])
        if not isinstance(tokens, list):
            raise ProviderError()
        pieces, boundaries = [], []
        for token in tokens:
            token = _object(token)
            text, final = _text(token.get("text")), token.get("is_final")
            if not isinstance(final, bool):
                raise ProviderError()
            if text == "<end>":
                if not final:
                    raise ProviderError()
                boundaries.append(len(pieces))
                continue
            status = token.get("translation_status", "none")
            if status not in {"none", "original", "translation"}:
                raise ProviderError()
            pieces.append(StreamPiece(text, final, status == "translation", token.get("language"), token.get("speaker"),
                                      _time(token.get("start_ms"), 1000), _time(token.get("end_ms"), 1000), status))
        return StreamUpdate(tuple(pieces), done=message.get("finished") is True,
                            endpoint=bool(boundaries), boundaries=tuple(boundaries))


class SpeechmaticsProtocol:
    name = "speechmatics"
    wait_for_ready = True

    def __init__(self, *, model="enhanced", region="global", terms=()):
        if model not in {"enhanced", "melia-1"} or region not in {"global", "eu", "us", "au"}:
            raise ValueError("Choose a verified Speechmatics model and region")
        self.model, self.terms = model, _terms(terms)
        self.endpoint = f"wss://{region}.rt.speechmatics.com/v2/"

    def headers(self, credentials):
        return {"Authorization": "Bearer " + provider_key(credentials, self.name)}

    def start(self):
        config = {"model": self.model, "language": "ar_en" if self.model == "enhanced" else "multi",
                  "enable_partials": True, "max_delay": .7, "diarization": "speaker"}
        if self.model == "enhanced":
            config["additional_vocab"] = list(self.terms)
            config["conversation_config"] = {"end_of_utterance_silence_trigger": .6}
        else:
            # Melia rejects Enhanced's conversation_config; the runner must use
            # local VAD and ForceEndOfUtterance for the low-latency comparison.
            config["language_hints"] = ["en", "ar"]
        return {"message": "StartRecognition", "audio_format": {"type": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                "transcription_config": config}

    def audio(self, pcm):
        return bytes(pcm)

    def finish(self, frame_count):
        return {"message": "EndOfStream", "last_seq_no": frame_count}

    def parse(self, message):
        message = _object(message)
        kind = message.get("message")
        if kind == "Error":
            _error("quota_exceeded" if message.get("type") == "quota_exceeded" else None)
        if kind not in {"AddTranscript", "AddPartialTranscript"}:
            return StreamUpdate(ready=kind == "RecognitionStarted", done=kind == "EndOfTranscript",
                                endpoint=kind == "EndOfUtterance", warning=kind == "Warning")
        metadata = _object(message.get("metadata"))
        return StreamUpdate((StreamPiece(_text(metadata.get("transcript")), kind == "AddTranscript",
                             start_s=_time(metadata.get("start_time")), end_s=_time(metadata.get("end_time"))),))


class ElevenLabsProtocol:
    name = "elevenlabs"
    wait_for_ready = True
    model = "scribe_v2_realtime"

    def __init__(self, *, terms=(), allow_keyterm_premium=False):
        self.terms = _terms(terms)
        if self.terms and not allow_keyterm_premium:
            raise ValueError("ElevenLabs keyterms add a premium; verify and explicitly approve its account price first")
        params = [("model_id", self.model), ("audio_format", "pcm_16000"), ("commit_strategy", "vad"),
                  ("vad_silence_threshold_secs", "0.6"), ("include_timestamps", "true"),
                  ("include_language_detection", "true"), ("secondary_languages", "en"), ("secondary_languages", "ar")]
        params.extend(("keyterms", term) for term in self.terms)
        self.endpoint = "wss://api.elevenlabs.io/v1/speech-to-text/realtime?" + urlencode(params)

    def headers(self, credentials):
        return {"xi-api-key": provider_key(credentials, self.name)}

    def start(self):
        return None  # Handshake query selects the audio/model configuration.

    def audio(self, pcm):
        return {"message_type": "input_audio_chunk", "audio_base_64": base64.b64encode(pcm).decode("ascii"), "sample_rate": 16000}

    def finish(self, frame_count):
        return {"message_type": "input_audio_chunk", "audio_base_64": "", "commit": True, "sample_rate": 16000}

    def parse(self, message):
        message = _object(message)
        kind = message.get("message_type", "")
        if kind.endswith("error") or kind in {"rate_limited", "throttled", "quota_exceeded"}:
            _error(kind)
        if kind in {"partial_transcript", "committed_transcript"}:
            return StreamUpdate((StreamPiece(_text(message.get("text")), kind == "committed_transcript"),))
        if kind == "committed_transcript_with_timestamps":
            words = message.get("words")
            words = [] if words is None else words
            if not isinstance(words, list):
                raise ProviderError()
            starts, ends, speakers, complete = [], [], [], True
            for word in words:
                word = _object(word)
                start, end = _time(word.get("start")), _time(word.get("end"))
                if start is not None and end is not None and end < start:
                    raise ProviderError()
                if word.get("type", "word") != "word":
                    continue  # Spacing/audio-event timing isn't speech-end timing.
                complete = complete and start is not None and end is not None
                if start is not None:
                    starts.append(start)
                if end is not None:
                    ends.append(end)
                speaker = word.get("speaker_id")
                if isinstance(speaker, str) and speaker not in speakers:
                    speakers.append(speaker)
            language = message.get("language_code")
            language = {"ara": "ar", "eng": "en"}.get(language, language) if isinstance(language, str) else None
            language = language if language in {"ar", "en"} else None
            annotation = StreamPiece(_text(message.get("text")), True, language=language,
                speaker=speakers[0] if len(speakers) == 1 else None,
                start_s=min(starts) if starts and complete else None,
                end_s=max(ends) if ends and complete else None)
            # Metadata never becomes another source/MT event.
            return StreamUpdate(annotations=(annotation,))
        return StreamUpdate(ready=kind == "session_started", warning=kind == "warning")
