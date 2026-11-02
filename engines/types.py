from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from engines.usage import Units

import numpy as np


@dataclass
class AsrResult:
    text: str
    language: str | None
    language_prob: float | None
    language_tag: str
    latin_ratio: float
    avg_logprob: float | None
    no_speech_prob: float | None
    duration_s: float
    provider: str


@dataclass
class MtResult:
    text: str
    provider: str
    billed_chars: int = 0
    usage: "Units | None" = None


class SpeechRecognizer(Protocol):
    name: str
    requires_network: bool

    def transcribe(self, audio: np.ndarray, sample_rate: int, *,
                   hint_language: str | None, prompt: str | None,
                   stop_event: Event | None) -> AsrResult: ...


class Translator(Protocol):
    name: str
    requires_network: bool

    def supports(self, source: str, target: str) -> bool: ...

    def translate(self, text: str, source: str, target: str, *,
                  context: list[tuple[str, str]], glossary: dict[str, str]) -> MtResult: ...


class StreamingInterpreter(Protocol):
    def start(self, conversation: tuple[str, str], output_language: str,
              two_way: bool, on_event: Callable) -> None: ...

    def push_audio(self, pcm16k_mono_f32: np.ndarray) -> None: ...

    def stop(self) -> None: ...
