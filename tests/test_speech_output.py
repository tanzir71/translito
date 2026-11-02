import numpy as np
import threading

from speech_output import SpeechOutputPlayer, resample_audio


def test_resample_audio_changes_length_and_keeps_float32():
    audio = np.linspace(-0.5, 0.5, 48000, dtype=np.float32)

    resampled = resample_audio(audio, 48000, 16000)

    assert resampled.dtype == np.float32
    assert len(resampled) == 16000
    assert np.isclose(float(resampled[0]), -0.5)


def test_resample_audio_returns_same_array_shape_when_rates_match():
    audio = np.linspace(-0.25, 0.25, 100, dtype=np.float32)

    resampled = resample_audio(audio, 16000, 16000)

    assert resampled.dtype == np.float32
    assert np.array_equal(resampled, audio)


def test_stop_restart_never_plays_stale_synthesis_or_clears_new_playing_state():
    old_started, release_old = threading.Event(), threading.Event()
    new_started, release_new = threading.Event(), threading.Event()
    played = []

    class SlowSynthesizer:
        def synthesize(self, text, language, voice):
            assert text == "old"
            old_started.set()
            assert release_old.wait(4)
            return np.zeros(1600, dtype=np.float32), 16000

    player = SpeechOutputPlayer(synthesizer=SlowSynthesizer())

    def play(samples, rate, stop_event=None):
        played.append(float(samples[0]))
        new_started.set()
        assert release_new.wait(4)

    player._play = play
    try:
        player.enqueue("old", "en")
        assert old_started.wait(1)
        old_thread = player._thread
        player.enqueue("queued old text", "en")
        player.stop(join_timeout=0.01)
        player.enqueue_audio(np.ones(1600, dtype=np.float32), 16000)
        assert new_started.wait(1)
        assert player.is_playing
        release_old.set()
        old_thread.join(timeout=1)
        assert not old_thread.is_alive()
        assert player.is_playing  # the old worker's finally cannot clear this
        assert played == [1.0]
    finally:
        release_old.set()
        release_new.set()
        player.stop()
    assert not player.is_playing


def test_route_retry_resamples_to_the_rebound_device_rate():
    written = []

    class Stream:
        def write(self, data):
            written.append(data)

        def stop(self):
            pass

        def close(self):
            pass

    player = SpeechOutputPlayer()
    player._open_stream = lambda *_: (Stream(), 48000)
    player._retry_write(None, "CABLE Input", np.ones(1600, dtype=np.float32), sample_rate=16000)
    assert len(written[0]) == 4800
    stopped = threading.Event()
    stopped.set()
    player._retry_write(None, "CABLE Input", np.ones(1600, dtype=np.float32), sample_rate=16000,
                        stop_event=stopped)
    assert len(written) == 1
