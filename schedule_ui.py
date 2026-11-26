"""Schedule controls and tray-resident polling; calendar URLs never enter config."""
from ui_scale import px, scaled_geometry
from datetime import datetime, timedelta, timezone
import json
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from engines.schedule import CalendarFeed, Scheduler, weekly_meetings


class ScheduleController:
    def __init__(self, app, colors):
        self.app, self.colors, self.feed = app, colors, None
        self.events, self.refreshing, self.next_refresh = [], False, None
        self.checked_events = set()
        self.device_probe, self.device_probe_busy, self.device_probe_at = (None, False), False, 0
        self.scheduler = Scheduler(clock=lambda:datetime.now(timezone.utc), running=lambda:app.transcriber is not None or app.model_setup_busy or getattr(app, "_waiting_meeting_app", False),
            start_listen=self.start_listen, stop=app.stop, app_has_audio=self.app_has_audio, notice=self.toast,
            session_state=self.session_state,
            confirm=lambda event:messagebox.askyesno("Scheduled meeting", "Start listening for this meeting?", parent=app.root))
        from engines.weekly_schedule import local_timezone, migrate_entries
        pc_zone = local_timezone()
        config = app.preferences.store.read()
        if not config.has_option("SCHEDULE", "weekly_blocks"):
            old = json.loads(config.get("SCHEDULE", "weekly_times", fallback="[]"))
            blocks, changed = migrate_entries(old, config.get("SCHEDULE", "timezone", fallback="UTC"), pc_zone)
            if not blocks:
                blocks = [dict(days=[0,1,2,3,4],start="09:30",end="18:00",timezone=pc_zone,title="Workdays")]
            app.preferences.set("SCHEDULE", "weekly_blocks", json.dumps(blocks))
            if changed:
                app.preferences.set("SCHEDULE", "timezone", pc_zone)
                app.preferences.set("SCHEDULE", "timezone_notice", f"Weekly times now use your PC's time zone ({pc_zone}). Check them in Settings › Schedule.")
        if not app.preview_mode and "blocks" in locals():
            changes = {("SCHEDULE", "weekly_blocks"): json.dumps(blocks)}
            if changed:
                changes["SCHEDULE", "timezone"] = pc_zone
                changes["SCHEDULE", "timezone_notice"] = f"Weekly times now use your PC's time zone ({pc_zone}). Check them in Settings › Schedule."
            app.preferences.store.update(changes, sync=True)
        self.variables = {}
        for key, default in (("enabled", False), ("source", "weekly"), ("weekly_times", "[]"), ("weekly_blocks", json.dumps(blocks) if "blocks" in locals() else "[]"), ("skipped", "[]"), ("lead_seconds", 60),
            ("stop_rule", "end"), ("silence_seconds", 300), ("wait_for_app_audio", True), ("ask_before_start", False),
            ("only_with_call_link", False), ("timezone", pc_zone)):
            var = tk.BooleanVar(app.root) if isinstance(default,bool) else tk.IntVar(app.root) if isinstance(default,int) else tk.StringVar(app.root)
            self.variables[key] = app.preferences.bind(var, "SCHEDULE", key, default)
        app.next_meeting_var = tk.StringVar()
        tk.Label(app.status_bar, textvariable=app.next_meeting_var, bg=colors["bg"], fg=colors["tertiary"], font=("Segoe UI", 8), anchor="w").grid(row=1,column=1,columnspan=4,sticky="w",pady=px((3,0)))
        self.timer = app.root.after(1000, self.tick)

    def app_has_audio(self):
        app = self.app
        if app.preview_mode:
            return False
        from engines.process_audio import active_sources
        from meeting_app import resolve_default_app
        try:
            if app.listen_source_type_var.get() == "Device":
                choice = app.selected_listen_choice()
                if choice is None:
                    return False
                import time
                if not self.device_probe_busy and time.monotonic() >= self.device_probe_at:
                    self.device_probe_busy, self.device_probe_at = True, time.monotonic() + 3
                    def probe():
                        audible = False
                        try:
                            import numpy as np
                            with choice.raw.recorder(samplerate=16000) as recorder:
                                sample = recorder.record(numframes=1600)
                            audible = float(np.sqrt(np.mean(np.asarray(sample) ** 2))) > .001
                        except Exception:
                            pass
                        self.device_probe, self.device_probe_busy = (choice.name, audible), False
                    threading.Thread(target=probe, daemon=True, name="Check selected device activity").start()
                return self.device_probe == (choice.name, True)
            from meeting_app import preferred_app
            desired = preferred_app(app)
            sources = active_sources()
            return any(not source.exclude for source in sources) if desired in {"", "*"} else resolve_default_app(desired, sources) is not None
        except Exception:
            return False

    def start_listen(self):
        self.app.set_mode("listen", force=True)
        self.app.subtitles_enabled_var.set(True)
        return self.app.start(owner="schedule:" + self.scheduler.pending.id)

    def session_state(self, event):
        controller = getattr(self.app, "session_controller", None)
        if controller is None:
            return "idle"
        owner = "schedule:" + event.id
        if self.app.transcriber is not None and controller.active_owner == owner:
            return "running"
        if controller.pending and controller.pending[1] == owner:
            return "pending"
        if getattr(self.app, "_waiting_meeting_app", False) and getattr(self.app, "_waiting_owner", None) == owner:
            return "pending"
        return "idle"

    def calendar_feed(self):
        if self.feed is None:
            from engines.secrets import CredentialStore
            self.feed = CalendarFeed(CredentialStore())
        return self.feed

    def tick(self):
        app, values = self.app, self.variables
        if app.is_quitting:
            return
        now = datetime.now(timezone.utc)
        if values["enabled"].get() and not app.preview_mode:
            if values["source"].get() == "weekly":
                try:
                    self.events = weekly_meetings(json.loads(values["weekly_blocks"].get()), now-timedelta(days=1), now+timedelta(days=7), default_timezone=values["timezone"].get())
                except (ValueError, KeyError, TypeError):
                    self.events = []
            if values["source"].get() != "weekly":
                due = {event.id for event in self.events if event.start-timedelta(seconds=values["lead_seconds"].get()) <= now < event.end}
                if due - self.checked_events and not self.refreshing:
                    self.next_refresh = None
            if values["source"].get() != "weekly" and not self.refreshing and not app.offline_only_var.get() and (self.next_refresh is None or now >= self.next_refresh):
                self.refreshing, self.next_refresh = True, now+timedelta(minutes=15)
                def refresh():
                    try:
                        feed = self.calendar_feed()
                        if app.offline_only_var.get():
                            return
                        feed.next_refresh = 0
                        self.events = feed.meetings(now-timedelta(days=1), now+timedelta(days=7))
                        self.checked_events.update(due)
                        if not feed.healthy:
                            self.next_refresh = now+timedelta(seconds=30)
                    except Exception:
                        self.events = []
                        self.next_refresh = now+timedelta(seconds=30)
                    finally:
                        self.refreshing = False
                threading.Thread(target=refresh, daemon=True).start()
            try:
                skips = [item for item in json.loads(values["skipped"].get()) if datetime.fromisoformat(item["end"]) > now]
                if json.dumps(skips) != values["skipped"].get():
                    values["skipped"].set(json.dumps(skips))
            except (ValueError, KeyError, TypeError):
                skips = []
            eligible = self.events if values["source"].get() == "weekly" or (not app.offline_only_var.get() and not self.refreshing and self.feed and self.feed.healthy) else []
            self.scheduler.tick(eligible, skipped={item["id"] for item in skips}, **{key:var.get() for key,var in values.items() if key in {
                "enabled", "lead_seconds", "wait_for_app_audio", "stop_rule", "silence_seconds", "ask_before_start", "only_with_call_link"}})
        elif self.scheduler.active or self.scheduler.pending:
            self.scheduler.tick([], enabled=False)
        coming = next((event for event in self.events if event.end > now), None) if values["enabled"].get() else None
        app.next_meeting_var.set("Next meeting · "+coming.start.astimezone().strftime("%a %H:%M") if coming else "")
        self.timer = app.root.after(1000, self.tick)

    def toast(self, event):
        window = tk.Toplevel(self.app.root)
        from windows_icons import apply_window_icon
        window.after_idle(lambda: apply_window_icon(window))
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=self.colors["surface"], padx=px(14), pady=px(12))
        tk.Label(window, text=("" if getattr(event, "download", False) else "Scheduled listening · ")+event.title, bg=self.colors["surface"], fg=self.colors["text"], wraplength=px(340), justify="left").pack(fill="x")
        actions = tk.Frame(window,bg=self.colors["surface"])
        actions.pack(fill="x",pady=px((8,0)))
        download = getattr(event, "download", False)
        def dismiss_or_stop():
            if not download and self.session_state(event) == "running":
                self.app.stop()
            window.destroy()
        ttk.Button(actions,text="Dismiss" if download else "Stop",style="Mac.TButton",command=dismiss_or_stop).pack(side="left")
        ttk.Button(actions,text="Models" if download else "Settings",style="Mac.TButton",command=lambda:(self.app.show_settings_from_tray(),self.app.settings_shell.show("Models" if download else "Schedule"),window.destroy())).pack(side="right")
        window.geometry(f"{px(380)}x{px(110)}+{max(0,self.app.root.winfo_screenwidth()-px(400))}+{px(30)}")
        window.after(12000,window.destroy)


def page(app, colors):
    from weekly_schedule_ui import page as workday_page
    workday_page(app, colors)
    notice = app.preferences.get("SCHEDULE", "timezone_notice", "")
    if notice:
        app.show_hint(notice)
        app.preferences.set("SCHEDULE", "timezone_notice", "")
