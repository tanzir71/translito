from engines.process_audio import ProcessSource
from meeting_app import resolve_default_app


def test_default_app_resolves_after_pid_changes_and_never_broadens_to_all_apps():
    all_apps = ProcessSource(1, 1, "All apps", exclude=True)
    old = ProcessSource(10, 100, "Zoom (PID 10)", executable="Zoom.exe")
    new = ProcessSource(20, 200, "Zoom (PID 20)", executable="Zoom.exe")
    assert resolve_default_app("zoom.exe", [all_apps, old]) == old
    assert resolve_default_app("zoom.exe", [all_apps, new]) == new
    assert resolve_default_app("zoom.exe", [all_apps]) is None
