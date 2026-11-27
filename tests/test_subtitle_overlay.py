from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from subtitle_overlay import Win32Overlay, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TRANSPARENT, SubtitleOverlay, Monitor


def test_overlay_styles_are_non_activating_layered_click_through_and_excluded_from_capture():
    user, gdi = Mock(), Mock()
    user.GetParent.return_value = 123
    user.GetWindowLongPtrW.return_value = 0
    gdi.CreateRoundRectRgn.return_value = 456
    window = SimpleNamespace(winfo_id=lambda: 12, winfo_width=lambda: 720, winfo_height=lambda: 90)
    layer = Win32Overlay(user32=user, gdi32=gdi)
    layer.apply(window, click_through=True, hide_from_capture=True)
    expected = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
    user.SetWindowLongPtrW.assert_called_with(123, -20, expected)
    user.SetWindowDisplayAffinity.assert_called_with(123, 0x11)
    layer.apply(window, click_through=False)
    assert user.SetWindowLongPtrW.call_args.args[2] & WS_EX_TRANSPARENT == 0


def test_monitor_position_keys_are_stable():
    assert SubtitleOverlay.position_key(Monitor("DISPLAY2", 1920, 0, 3840, 1080)) == "position_display2"


def test_per_monitor_position_survives_restart(tmp_path):
    from settings_state import SettingsState
    monitor = Monitor("DISPLAY2", 1920, 0, 3840, 1080)
    window = SimpleNamespace(winfo_x=lambda:2020,winfo_y=lambda:80,geometry=Mock())
    overlay = SimpleNamespace(window=window, root=None, monitor=monitor, preferences=SettingsState(tmp_path/"config.ini"),
        backend=SimpleNamespace(monitors=lambda root:[monitor]), position_key=SubtitleOverlay.position_key)
    SubtitleOverlay.drag_end(overlay, None)
    overlay.preferences = SettingsState(tmp_path/"config.ini")
    SubtitleOverlay.restore_position(overlay, monitor)
    window.geometry.assert_called_with("720x90+2020+80")


@pytest.fixture
def subtitles(tmp_path, tk_parent):
    from gui import COLORS
    from settings_state import SettingsState
    from subtitle_overlay import PreviewBackend
    preferences = SettingsState(tmp_path / "config.ini")
    preferences.set("SUBTITLES", "show_original", True)
    preferences.set("SUBTITLES", "text_size", 24)
    overlay = SubtitleOverlay(tk_parent, preferences, COLORS, backend=PreviewBackend())
    yield overlay
    preferences.close()
    overlay.window.destroy()


def points(label):
    from tkinter.font import Font
    return Font(label, font=label.cget("font")).actual("size")


@pytest.mark.parametrize('lines', [1, 2, 3])
def test_translation_stays_large_when_next_source_arrives(subtitles, lines):
    overlay = subtitles
    overlay.preferences.set("SUBTITLES", "lines", lines)
    translated = dict(id="first", source_text="مرحبا.", source_language="ar", target_language="en",
                      translated_text="Hello.", translation_pending=False)
    overlay.accept(translated)
    assert overlay.labels[0].cget("text") == "Hello."
    assert points(overlay.labels[0]) == 24
    assert points(overlay.labels[0]) > points(overlay.labels[3])
    overlay.accept(dict(id="next", source_text="الجملة التالية", source_language="ar", target_language="en",
                        translated_text="", translation_pending=True))
    assert overlay.labels[0].cget("text") == "Hello."
    assert points(overlay.labels[0]) == 24
    assert overlay.labels[3]._language_text[0] == translated["source_text"]
    overlay.accept(dict(id="next", translated_text="The next sentence.", translation_pending=True))
    primary = overlay.labels[min(lines, 2) - 1]
    assert primary.cget("text") == "The next sentence."
    assert points(primary) == 24 and points(primary) > points(overlay.labels[3])
    if lines > 1:
        assert overlay.labels[0].cget("text") == "Hello."
        assert points(primary) > points(overlay.labels[0])


def test_initial_source_is_secondary_until_translation_arrives(subtitles):
    overlay = subtitles
    entry = dict(id="draft", source_text="مرحبا.", source_language="ar", target_language="en",
                 translated_text="", translation_pending=True)
    overlay.accept(entry)
    assert points(overlay.labels[0]) < 24
    overlay.accept(dict(entry, translated_text="Hello."))
    assert overlay.labels[0].cget("text") == "Hello." and points(overlay.labels[0]) == 24


def test_multiple_pending_rows_do_not_evict_the_last_translation(subtitles):
    overlay = subtitles
    overlay.accept(dict(id='translated', source_text='مرحبا.', translated_text='Hello.',
                        source_language='ar', target_language='en', translation_pending=False))
    for index in range(6):
        overlay.accept(dict(id=f'pending-{index}', source_text='جملة جديدة', translated_text='',
                            source_language='ar', target_language='en', translation_pending=True))
    assert overlay.labels[0].cget('text') == 'Hello.' and points(overlay.labels[0]) == 24
    assert len(overlay.entries) <= 4


def test_same_language_speech_remains_primary_and_original_can_be_hidden(subtitles):
    overlay = subtitles
    overlay.preferences.set("SUBTITLES", "show_original", False)
    overlay.accept(dict(id="spoken", source_text="Already English.", source_language="en", target_language="en",
                        translated_text="", pass_through=True, translation_pending=False))
    assert overlay.labels[0].cget("text") == "Already English."
    assert points(overlay.labels[0]) == 24
    assert not overlay.labels[3].winfo_manager()
