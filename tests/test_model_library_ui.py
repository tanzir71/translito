from types import SimpleNamespace
from unittest.mock import Mock
import tkinter as tk

import pytest

from engines.model_library import ModelEntry, ModelSpec
from model_library_ui import ModelManagerWindow


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui(tmp_path, tk_root):
    root = tk_root
    model = tmp_path / "small"
    model.mkdir()
    spec = ModelSpec("small", "Whisper small", "Speech", "example/small", "ct2")
    downloaded = ModelEntry(spec, model, "App cache", "Downloaded", 1024, True, tmp_path)
    available = ModelEntry(ModelSpec("tiny", "Whisper tiny", "Speech", "example/tiny", "ct2"),
                           tmp_path / "tiny", "Available", "Available", 0, False, tmp_path)
    library = SimpleNamespace(download=Mock(), delete=Mock())
    app = SimpleNamespace(root=root, transcriber=None, model_setup_busy=False, preview_mode=False,
                          offline_only_var=tk.BooleanVar(root, value=False), is_quitting=False,
                          open_arabic_model_setup=Mock(), open_translation_model_setup=Mock())
    colors = dict(bg="#222222", surface="#252525", surface_2="#303033", text="white", secondary="#aaaaaa", blue="#0a84ff")
    manager = ModelManagerWindow(app, colors, lambda *a, **k: None, library=library, auto_refresh=False)
    manager.window.withdraw()
    manager.rows = {row.key: row for row in (downloaded, available)}
    manager.run = Mock()
    manager.render()
    yield SimpleNamespace(manager=manager, app=app, library=library, downloaded=downloaded, available=available)
    manager.window.destroy()


def select(ui, row):
    ui.manager.tree.selection_set(row.key)
    ui.manager.selection_changed()


def test_model_filters_and_disk_usage(ui):
    assert len(ui.manager.tree.get_children()) == 2
    assert ui.manager.tree.item(ui.downloaded.key, "values")[3] == "1.0 KB"
    ui.manager.filter.set("Downloaded"); ui.manager.render()
    assert ui.manager.tree.get_children() == (ui.downloaded.key,)
    ui.manager.filter.set("Available / partial"); ui.manager.render()
    assert ui.manager.tree.get_children() == (ui.available.key,)


@pytest.mark.parametrize("geometry", ["680x400", "900x580"])
def test_actions_stay_visible_above_the_list_when_window_shrinks(ui, geometry):
    window = ui.manager.window
    window.transient("")
    window.geometry(geometry)
    window.deiconify()
    window.update()
    select(ui, ui.downloaded)
    for button in (ui.manager.download_button, ui.manager.delete_button, ui.manager.folder_button):
        assert button.winfo_ismapped()
        x = button.winfo_rootx() - window.winfo_rootx()
        y = button.winfo_rooty() - window.winfo_rooty()
        assert x >= 0 and x + button.winfo_width() <= window.winfo_width()
        assert y >= 0 and y + button.winfo_height() <= window.winfo_height()
        assert button.winfo_rooty() + button.winfo_height() <= ui.manager.tree.winfo_rooty()
    assert not ui.manager.delete_button.instate(["disabled"])


def test_cancelled_confirmation_does_not_start_deletion(ui, monkeypatch):
    select(ui, ui.downloaded)
    monkeypatch.setattr("model_library_ui.messagebox.askyesno", Mock(return_value=False))
    ui.manager.delete()
    ui.manager.run.assert_not_called(); ui.library.delete.assert_not_called()
    monkeypatch.setattr("model_library_ui.messagebox.askyesno", Mock(return_value=True))
    ui.manager.delete()
    ui.manager.run.call_args.args[0]()
    ui.library.delete.assert_called_once_with(ui.downloaded, confirmed=True)


@pytest.mark.parametrize("state", ["session", "busy"])
def test_confirmation_rechecks_activity_before_starting_deletion(ui, monkeypatch, state):
    select(ui, ui.downloaded)
    def confirmed(*args, **kwargs):
        if state == "session":
            ui.app.transcriber = object()
        else:
            ui.app.model_setup_busy = True
        return True
    monkeypatch.setattr("model_library_ui.messagebox.askyesno", confirmed)
    ui.manager.delete()
    ui.manager.run.assert_not_called()
    ui.library.delete.assert_not_called()


@pytest.mark.parametrize("state", ["session", "busy", "preview", "scanning"])
def test_model_operations_are_blocked_in_active_or_preview_states(ui, monkeypatch, state):
    select(ui, ui.downloaded)
    if state == "session": ui.app.transcriber = object()
    elif state == "busy": ui.app.model_setup_busy = True
    elif state == "preview": ui.app.preview_mode = True
    else: ui.manager.scanning = True
    confirmation = Mock(return_value=True)
    monkeypatch.setattr("model_library_ui.messagebox.askyesno", confirmation)
    ui.manager.delete(); ui.manager.download()
    ui.manager.run.assert_not_called(); confirmation.assert_not_called()


def test_downloads_obey_offline_setting_and_gated_setup(ui):
    select(ui, ui.available)
    ui.app.offline_only_var.set(True)
    ui.manager.download(); ui.manager.run.assert_not_called()
    assert "Offline" in ui.manager.status.get()
    ui.app.offline_only_var.set(False)
    ui.manager.download(); ui.manager.run.call_args.args[0]()
    ui.library.download.assert_called_once()
    ui.manager.run.reset_mock()
    spec = ModelSpec("cohere", "Cohere", "Speech", "owner/gated", "transformers", setup="cohere")
    row = ModelEntry(spec, ui.available.path, "Available", "Available", 0, False, ui.available.root)
    ui.manager.rows = {row.key: row}; ui.manager.filter.set("All models"); ui.manager.render(); select(ui, row)
    ui.manager.download()
    ui.app.open_arabic_model_setup.assert_called_once(); ui.manager.run.assert_not_called()
