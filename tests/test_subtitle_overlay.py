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
        backend=SimpleNamespace(monitors=lambda root:[monitor]), position_key=SubtitleOverlay.position_key, fit_to_monitor=Mock())
    SubtitleOverlay.drag_end(overlay, None)
    overlay.preferences = SettingsState(tmp_path/"config.ini")
    SubtitleOverlay.restore_position(overlay, monitor)
    assert overlay._preferred_position == (2020, 80)
    overlay.fit_to_monitor.assert_called_once()


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


def test_original_off_hides_native_drafts_until_translation_arrives(subtitles):
    overlay = subtitles
    overlay.preferences.set('SUBTITLES','show_original',False)
    entry = dict(id='draft',source_text='مرحبا.',source_language='ar',target_language='en',
                 translated_text='',translation_pending=True)
    overlay.accept(entry)
    assert not any(label.winfo_manager() for label in overlay.labels)
    overlay.visible(True,listening=True,minimized=False)
    assert overlay.window.state() == 'withdrawn'
    overlay.accept(dict(entry,translated_text='Hello.'))
    overlay.visible(True,listening=True,minimized=False)
    assert overlay.labels[0].cget('text') == 'Hello.'
    assert not overlay.labels[3].winfo_manager()


@pytest.mark.parametrize('monitor', [Monitor('small', 0, 0, 800, 560), Monitor('left', -1000, -200, 0, 500)])
def test_long_subtitles_scroll_inside_the_work_area_and_restore_position(subtitles, monitor):
    overlay = subtitles
    overlay.monitor = monitor
    overlay._preferred_position = monitor.left + 30, monitor.bottom - 100
    overlay.preferences.set('SUBTITLES', 'text_size', 48)
    for index in range(3):
        overlay.accept(dict(id=str(index), source_text='مرحبا. ' * 200,
            source_language='ar', target_language='en', translated_text='A long translated sentence. ' * 180))
    overlay.window.deiconify()
    overlay.window.update()
    def inside():
        x, y = overlay.window.winfo_x(), overlay.window.winfo_y()
        assert monitor.left <= x and x + overlay.window.winfo_width() <= monitor.right
        assert monitor.top <= y and y + overlay.window.winfo_height() <= monitor.bottom
    inside()
    assert overlay.scrollbar.winfo_manager() == 'pack'
    assert overlay.canvas.yview()[0] > 0
    overlay.canvas.yview_moveto(0)
    assert overlay.canvas.yview()[0] == 0
    overlay.render()
    assert overlay.canvas.yview()[0] == 0  # Ticks do not undo the reader's scroll.
    overlay.toolbar.pack(fill='x', before=overlay.viewport)
    overlay.fit_to_monitor()
    inside()
    overlay.entries.clear()
    overlay.accept(dict(id='short', source_text='مرحبا.', translated_text='Hello.', source_language='ar',target_language='en'))
    inside()
    assert not overlay.scrollbar.winfo_manager()


def test_overlay_monitor_api_is_not_changed_by_dialog_centering(subtitles):
    import sys, ctypes
    if sys.platform != 'win32':
        pytest.skip('Windows monitor API')
    backend = Win32Overlay()
    shared = ctypes.windll.user32.GetMonitorInfoW
    original = shared.argtypes
    try:
        shared.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        monitors = backend.monitors(subtitles.root)
        assert monitors and monitors[0].right > monitors[0].left
        assert backend.user32.GetMonitorInfoW.argtypes == [ctypes.c_void_p, ctypes.c_void_p]
    finally:
        shared.argtypes = original
