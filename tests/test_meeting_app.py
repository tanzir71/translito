from engines.process_audio import ProcessSource
from meeting_app import resolve_default_app
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


def variable(initial):
    state = [initial]
    return SimpleNamespace(get=lambda:state[0],set=lambda value:state.__setitem__(0,value))


def host(tmp_path, kind="App audio"):
    from settings_state import SettingsState
    return SimpleNamespace(mode_var=variable("listen"),listen_source_type_var=variable(kind),
        default_app_var=variable("Zoom.exe"),if_app_closed_var=variable("wait"),transcriber=None,
        preferences=SettingsState(tmp_path/"config.ini"),_waiting_meeting_app=False,_meeting_timer=None,is_quitting=False,
        root=SimpleNamespace(after=Mock(return_value="poll"),after_cancel=Mock()),set_status=Mock(),show_hint=Mock(),show_error=Mock(),
        refresh_devices=Mock(),listen_choices=[],listen_combo=SimpleNamespace(configure=Mock(),current=Mock()),start=Mock())


def test_default_app_resolves_after_pid_changes_and_never_broadens_to_all_apps():
    all_apps = ProcessSource(1, 1, "All apps", exclude=True)
    old = ProcessSource(10, 100, "Zoom (PID 10)", executable="Zoom.exe")
    new = ProcessSource(20, 200, "Zoom (PID 20)", executable="Zoom.exe")
    assert resolve_default_app("zoom.exe", [all_apps, old]) == old
    assert resolve_default_app("zoom.exe", [all_apps, new]) == new
    assert resolve_default_app("zoom.exe", [all_apps]) is None


@pytest.mark.parametrize("default_open", [False,True])
def test_device_selection_bypasses_default_meeting_app_and_cancels_wait(tmp_path, monkeypatch, default_open):
    from meeting_app import prepare_source
    import engines.process_audio
    app = host(tmp_path,"Device")
    device = object()
    app.selected_device = device
    app._waiting_meeting_app, app._meeting_timer = True, "old-poll"
    sources = Mock(return_value=[ProcessSource(10,100,"Zoom",executable="Zoom.exe")] if default_open else [])
    monkeypatch.setattr(engines.process_audio,"active_sources",sources)
    assert prepare_source(app)
    sources.assert_not_called(); app.refresh_devices.assert_not_called()
    assert app.selected_device is device and app.listen_source_type_var.get() == "Device"
    assert not app._waiting_meeting_app and app._meeting_timer is None
    app.root.after_cancel.assert_called_once_with("old-poll")


def test_explicit_app_selection_takes_priority_and_resolves_its_new_pid(tmp_path, monkeypatch):
    from meeting_app import prepare_source
    import engines.process_audio
    app = host(tmp_path)
    app.preferences.set("CAPTURE","app_executable","chrome.exe")
    browser = ProcessSource(24,200,"Chrome",executable="chrome.exe")
    monkeypatch.setattr(engines.process_audio,"active_sources",lambda:[ProcessSource(10,100,"Zoom",executable="Zoom.exe"),browser])
    assert prepare_source(app) and app.meeting_source == browser
    assert app.listen_source_type_var.get() == "App audio"
    assert app.listen_choices[0].raw is browser


def test_explicit_all_apps_is_not_replaced_by_the_default(tmp_path, monkeypatch):
    from meeting_app import prepare_source
    import engines.process_audio
    app = host(tmp_path)
    app.preferences.set("CAPTURE","app_executable","*")
    sources = Mock()
    monkeypatch.setattr(engines.process_audio,"active_sources",sources)
    assert prepare_source(app)
    sources.assert_not_called()


def test_default_app_wait_is_only_used_in_app_capture(tmp_path, monkeypatch):
    from meeting_app import prepare_source
    import engines.process_audio
    app = host(tmp_path)
    monkeypatch.setattr(engines.process_audio,"active_sources",lambda:[])
    assert not prepare_source(app)
    assert app._waiting_meeting_app and app._meeting_timer == "poll"
    app.root.after.call_args.args[1]()
    app.start.assert_called_once()
