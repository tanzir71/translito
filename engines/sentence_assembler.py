"""Join partial utterances without crossing language changes."""
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class Sentence:
    text: str
    language_tag: str
    parts: tuple


class SentenceAssembler:
    terminal = (".", "?", "!", "؟", "。")

    def __init__(self, idle_seconds=1.5, max_characters=220, clock=time.monotonic):
        self.idle_seconds = idle_seconds
        self.max_characters = max_characters
        self.clock = clock
        self.pending = []
        self.language_tag = None
        self.updated_at = None

    @property
    def text(self):
        return " ".join(text for text, _ in self.pending)

    def push(self, text, language_tag, part=None):
        completed = []
        if self.pending and self.language_tag != language_tag:
            completed.extend(self.flush())
        if not text.strip():
            return completed
        self.language_tag = language_tag
        self.pending.append((text.strip(), part))
        self.updated_at = self.clock()
        if self.text.endswith(self.terminal) or len(self.text) >= self.max_characters:
            completed.extend(self.flush())
        return completed

    def poll(self):
        if self.pending and self.clock() - self.updated_at >= self.idle_seconds:
            return self.flush()
        return []

    def flush(self):
        if not self.pending:
            return []
        sentence = Sentence(self.text, self.language_tag, tuple(part for _, part in self.pending))
        self.pending = []
        self.updated_at = None
        return [sentence]
