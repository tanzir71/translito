import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from engines.router import Conversation, route_utterance
from speech_output import BufferedVoice, SpeechOutputPlayer


def test_arabic_voice_passes_through_resampled_without_tts(monkeypatch):
    import device_utils
    written = []

    class Stream:
        def __init__(self, **kwargs):
            assert kwargs["samplerate"] == 48000

        def start(self):
            pass

        def write(self, audio):
            written.append(audio.copy())

        def stop(self):
            pass

        def close(self):
            pass

    fake_sd = SimpleNamespace(query_devices=lambda *args: {"default_samplerate": 48000}, OutputStream=Stream)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(device_utils, "resolve_output_device_index", lambda name: 0)
    synthesizer = Mock(side_effect=AssertionError("Arabic pass-through must not call TTS"))
    player = SpeechOutputPlayer(output_device_name="CABLE Input", synthesizer=synthesizer)
    player._running = True
    audio = np.linspace(-0.2, 0.2, 400, dtype=np.float32)
    route = route_utterance("ar", "speak", Conversation())
    assert route.speech == "passthrough" and not route.translate
    player.enqueue_audio(audio, 16000)
    original_play = player._play

    def play_and_stop(samples, rate, **kwargs):
        original_play(samples, rate, **kwargs)
        player._running = False

    player._play = play_and_stop
    player._worker()
    assert len(np.concatenate(written)) == 1200
    np.testing.assert_allclose(np.concatenate(written)[[0, -1]], audio[[0, -1]])
    synthesizer.synthesize.assert_not_called()


def test_pass_through_buffer_is_copied_from_capture_memory():
    player = SpeechOutputPlayer()
    player._running = True
    audio = np.ones(1600, dtype=np.float32)
    player.enqueue_audio(audio, 16000)
    audio[:] = 0
    item = player._queue.get_nowait()
    assert isinstance(item, BufferedVoice)
    assert np.all(item.samples == 1)
