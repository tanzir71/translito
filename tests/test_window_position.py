from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui import center_window


@pytest.mark.parametrize("parent_x,parent_y,expected", [
    (0, 0, "900x580+0+0"),
    (1000, 550, "900x580+380+140"),
    (250, 100, "900x580+180+90"),
])
def test_centered_dialog_remains_inside_desktop(parent_x, parent_y, expected):
    window = SimpleNamespace(update_idletasks=Mock(), geometry=Mock(),
                             winfo_vrootx=lambda: 0, winfo_vrooty=lambda: 0,
                             winfo_vrootwidth=lambda: 1280, winfo_vrootheight=lambda: 720)
    parent = SimpleNamespace(update_idletasks=Mock(), winfo_exists=lambda: True,
                             winfo_viewable=lambda: True, winfo_x=lambda: parent_x,
                             winfo_y=lambda: parent_y, winfo_width=lambda: 760,
                             winfo_height=lambda: 560)
    center_window(window, parent, 900, 580)
    window.geometry.assert_called_once_with(expected)


def test_standalone_window_uses_monitor_work_area_and_keeps_its_size(monkeypatch):
    monkeypatch.setattr("gui.window_work_area", lambda *args: (0, 0, 1920, 1040))
    window = SimpleNamespace(update_idletasks=Mock(), geometry=Mock(),
        winfo_width=lambda: 800, winfo_height=lambda: 640,
        winfo_reqwidth=lambda: 900, winfo_reqheight=lambda: 700)
    center_window(window)
    window.geometry.assert_called_once_with("800x640+560+200")


def test_hidden_parent_uses_screen_center(monkeypatch):
    monkeypatch.setattr("gui.window_work_area", lambda *args: (1280, 0, 2560, 1024))
    window = SimpleNamespace(update_idletasks=Mock(), geometry=Mock())
    parent = SimpleNamespace(update_idletasks=Mock(), winfo_exists=lambda: True, winfo_viewable=lambda: False)
    center_window(window, parent, 800, 640)
    window.geometry.assert_called_once_with("800x640+1520+192")


def test_child_uses_parent_monitor_and_clamps_to_its_work_area(monkeypatch):
    monkeypatch.setattr("gui.window_work_area", lambda *args: (-1920, 0, 0, 1040))
    window = SimpleNamespace(update_idletasks=Mock(), geometry=Mock())
    parent = SimpleNamespace(update_idletasks=Mock(), winfo_exists=lambda: True,
        winfo_viewable=lambda: True, winfo_x=lambda: -1800, winfo_y=lambda: 800,
        winfo_width=lambda: 800, winfo_height=lambda: 640)
    center_window(window, parent, 560, 420)
    window.geometry.assert_called_once_with("560x420+-1680+620")


def test_child_dialog_uses_only_a_visible_settings_parent():
    from gui import dialog_parent
    root = object()
    settings = SimpleNamespace(winfo_exists=lambda: True, winfo_viewable=lambda: False)
    app = SimpleNamespace(root=root, settings_window=settings)
    assert dialog_parent(app) is root
    settings.winfo_viewable = lambda: True
    assert dialog_parent(app) is settings
