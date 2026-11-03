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
