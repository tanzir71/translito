from types import SimpleNamespace
from unittest.mock import Mock
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
