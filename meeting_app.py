"""Resolve a meeting app by executable name; PIDs are session-only."""
from ui_scale import px, scaled_geometry
import tkinter as tk
from tkinter import ttk


def executable_name(source):
    return getattr(source, "executable", "") or source.name.split(" (PID", 1)[0].strip()


def resolve_default_app(executable, sources):
    return next((source for source in sources if not source.exclude and executable_name(source).casefold() == executable.casefold()), None)


def preferred_app(app):
    return app.preferences.get("CAPTURE", "app_executable", "") or app.default_app_var.get()


def cancel_wait(app):
    app._waiting_meeting_app = False
    if app._meeting_timer is not None:
        app.root.after_cancel(app._meeting_timer)
        app._meeting_timer = None


def initialize(app):
    app.default_app_var = app.preferences.bind(tk.StringVar(app.root), "CAPTURE", "default_app", "")
    app.if_app_closed_var = app.preferences.bind(tk.StringVar(app.root), "CAPTURE", "if_app_closed", "wait")
    app.meeting_source, app._waiting_meeting_app, app._meeting_timer = None, False, None


def page(app, colors):
    from engine_ui import heading, field
    parent = app.settings_shell.contents["Audio"]
    heading(parent, "Audio", "What Translito listens to, and where Speak mode sends your translated voice.", colors)
    picker = field(parent, "Default meeting app", app.default_app_var, colors, [app.default_app_var.get()])
    def refresh():
        if app.preview_mode:
            return
        from engines.process_audio import active_sources
        try:
            values = sorted({executable_name(source) for source in active_sources() if not source.exclude})
            picker.configure(values=["", *values])
        except Exception:
            app.show_hint("Meeting apps are unavailable. Refresh after the app starts playing audio.")
    ttk.Button(parent, text="Refresh meeting apps", command=refresh, style="Mac.TButton").pack(anchor="w", pady=px(6))
    field(parent, "If it is not open", app.if_app_closed_var, colors, ("wait", "everything"))
    tk.Label(parent, text="Browser meetings include all audio from that browser. The executable name is remembered after it restarts.",
        bg=colors["bg"], fg=colors["tertiary"], wraplength=px(560), justify="left", anchor="w").pack(fill="x", pady=px((6,16)))
    refresh()
    capture = field(parent,"Capture source",app.listen_source_type_var,colors,("Device","App audio"))
    capture.bind("<<ComboboxSelected>>",lambda _event:app.select_capture_source())
    app.settings_controls.append(capture)


def prepare_source(app):
    if app.mode_var.get() != "listen" or app.transcriber is not None:
        return True
    if app.listen_source_type_var.get() != "App audio":
        cancel_wait(app)
        return True
    preferred = preferred_app(app)
    if not preferred or preferred == "*":
        return True
    from engines.process_audio import active_sources
    from device_utils import InputDeviceChoice
    try:
        sources = active_sources()
        source = resolve_default_app(preferred, sources)
        explicit_app = app.preferences.get("CAPTURE", "app_executable", "")
        if source is None and not explicit_app and app.if_app_closed_var.get() == "everything":
            source = next((s for s in sources if s.exclude), None)
        if source is None:
            app._waiting_meeting_app = True
            app.set_status("Waiting for " + preferred)
            app.show_hint("Waiting for your meeting app to play audio. Stop cancels this wait.")
            if app._meeting_timer is not None:
                app.root.after_cancel(app._meeting_timer)
            def poll():
                app._meeting_timer = None
                if app._waiting_meeting_app and not app.is_quitting:
                    app.start()
            app._meeting_timer = app.root.after(1000, poll)
            return False
        cancel_wait(app)
        app.meeting_source = source
        app.refresh_devices()
        choice = InputDeviceChoice(source.name, source, True, False)
        app.listen_choices = [choice] + [item for item in app.listen_choices if item.raw != source]
        app.listen_combo.configure(values=[c.display_name for c in app.listen_choices])
        app.listen_combo.current(0)
        app.show_hint(executable_name(source) + " · your meeting app")
        return True
    except Exception:
        app.show_error("The default meeting app could not be resolved. Refresh it in Settings > Audio.")
        return False
