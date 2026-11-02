"""Per-call cancellation without mutating a shared model's session state."""
from contextlib import contextmanager
from contextvars import ContextVar


_stop_event = ContextVar("translation_stop_event", default=None)


class GenerationCancelled(RuntimeError):
    pass


def current_stop_event():
    return _stop_event.get()


def check_cancelled():
    event = current_stop_event()
    if event is not None and event.is_set():
        raise GenerationCancelled("Translation stopped.")


@contextmanager
def generation_scope(stop_event):
    token = _stop_event.set(stop_event)
    try:
        yield
    finally:
        _stop_event.reset(token)
