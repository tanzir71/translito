import numpy as np
import threading
import sys
from types import SimpleNamespace
from unittest.mock import Mock

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


def output_fixture(monkeypatch):
    import device_utils
    streams = []
    class Stream:
        def __init__(self, **kwargs):
            self.rate, self.device = kwargs["samplerate"], kwargs["device"]
            self.written, self.closed, self.aborted = [], False, False
            streams.append(self)
        def start(self):
            pass
        def write(self, data):
            self.written.append(data.copy())
        def stop(self):
            pass
        def abort(self):
            self.aborted = True
        def close(self):
            self.closed = True
    sd = SimpleNamespace(OutputStream=Stream, query_devices=lambda device, kind:
                         {"default_samplerate": 48000 if device == 0 else 44100})
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setattr(device_utils, "resolve_output_device_index", lambda name: 0 if name else None)
    return streams


def test_outputs_consume_equal_time_at_48k_and_44100_and_rebind_only_once(monkeypatch):
    streams = output_fixture(monkeypatch)
    player = SpeechOutputPlayer(output_device_name="CABLE Input", monitor=True)
    player._running = True
    # Fail just the first cable stream; later blocks must use the replacement.
    opened = player._open_stream
    def open_stream(sd, target):
        stream, rate = opened(sd, target)
        if len(streams) == 1:
            stream.write = Mock(side_effect=RuntimeError("route changed"))
        return stream, rate
    player._open_stream = open_stream
    player._play(np.ones(24000, dtype=np.float32), 24000)
    assert len(streams) == 3 and all(s.closed for s in streams)
    streams[0].write.assert_called_once()
    assert sum(len(x) for s in streams if s.device == 0 for x in s.written) == 48000
    assert sum(len(x) for s in streams if s.device is None for x in s.written) == 44100


def test_stream_keeps_devices_open_and_irregular_chunk_lengths_do_not_drift(monkeypatch):
    from speech_output import _PlaybackRoutes
    streams = output_fixture(monkeypatch)
    player = SpeechOutputPlayer(output_device_name="CABLE Input", monitor=True)
    player._running = True
    routes = _PlaybackRoutes(player)
    sample_count = 0
    for size in [1, 137, 2501, 7, 799, 24] * 20:
        routes.write(np.ones(size, dtype=np.float32), 24000)
        sample_count += size
    assert len(streams) == 2 and not any(s.closed for s in streams)
    routes.flush()
    for stream in streams:
        assert sum(map(len, stream.written)) == round(sample_count * stream.rate / 24000)
    routes.close()


def test_reconnect_discards_old_stream_audio_and_stop_cannot_autostart_from_late_callback(monkeypatch):
    streams = output_fixture(monkeypatch)
    player = SpeechOutputPlayer(output_device_name="CABLE Input", synthesizer=Mock())
    first_write, release_write, new_write = threading.Event(), threading.Event(), threading.Event()
    open_stream = player._open_stream
    def opening(sd, target):
        stream, rate = open_stream(sd, target)
        original = stream.write
        if len(streams) == 1:
            def slow(data):
                first_write.set()
                assert release_write.wait(3)
                original(data)
            stream.write = slow
        else:
            def write(data):
                original(data)
                new_write.set()
            stream.write = write
        return stream, rate
    player._open_stream = opening
    player.start()
    try:
        assert player.play_stream(np.full(2400, 100, dtype="<i2").tobytes())
        assert first_write.wait(1)
        player.play_stream(np.full(2400, 200, dtype="<i2").tobytes())
        player.reset_stream()
        assert streams[0].aborted
        player.play_stream(np.full(2400, 300, dtype="<i2").tobytes())
        release_write.set()
        assert new_write.wait(1)
        player.stop()
        assert len(streams) == 2 and all(stream.closed for stream in streams)
        assert all(not np.any(np.isclose(data, 200 / 32768)) for stream in streams for data in stream.written)
        player.synthesizer.synthesize.assert_not_called()
        assert not player.play_stream(np.zeros(2400, dtype="<i2").tobytes())
        assert not player._running
    finally:
        release_write.set()
        player.stop()
