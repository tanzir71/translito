"""Schedule controls and tray-resident polling; calendar URLs never enter config."""
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
        self.scheduler = Scheduler(clock=lambda:datetime.now(timezone.utc), running=lambda:app.transcriber is not None,
            start_listen=self.start_listen, stop=app.stop, app_has_audio=self.app_has_audio, notice=self.toast,
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
        tk.Label(app.status_bar, textvariable=app.next_meeting_var, bg=colors["bg"], fg=colors["tertiary"], font=("Segoe UI", 8), anchor="w").grid(row=1,column=1,columnspan=4,sticky="w",pady=(3,0))
        self.tick()

    def app_has_audio(self):
        if self.app.preview_mode or not self.app.default_app_var.get():
            return False
        from engines.process_audio import active_sources
        from meeting_app import resolve_default_app
        try:
            return resolve_default_app(self.app.default_app_var.get(), active_sources()) is not None
        except Exception:
            return False

    def start_listen(self):
        self.app.set_mode("listen", force=True)
        self.app.subtitles_enabled_var.set(True)
        self.app.start()

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
            elif not self.refreshing and (self.next_refresh is None or now >= self.next_refresh):
                self.refreshing, self.next_refresh = True, now+timedelta(minutes=15)
                def refresh():
                    try:
                        self.events = self.calendar_feed().meetings(now-timedelta(days=1), now+timedelta(days=7))
                    except Exception:
                        pass
                    finally:
                        self.refreshing = False
                threading.Thread(target=refresh, daemon=True).start()
            try:
                skips = [item for item in json.loads(values["skipped"].get()) if datetime.fromisoformat(item["end"]) > now]
                if json.dumps(skips) != values["skipped"].get():
                    values["skipped"].set(json.dumps(skips))
            except (ValueError, KeyError, TypeError):
                skips = []
            self.scheduler.tick(self.events, skipped={item["id"] for item in skips}, **{key:var.get() for key,var in values.items() if key in {
                "enabled", "lead_seconds", "wait_for_app_audio", "stop_rule", "silence_seconds", "ask_before_start", "only_with_call_link"}})
        elif self.scheduler.active:
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
        window.configure(bg=self.colors["surface"], padx=14, pady=12)
        tk.Label(window, text=("" if getattr(event, "download", False) else "Scheduled listening · ")+event.title, bg=self.colors["surface"], fg=self.colors["text"], wraplength=340, justify="left").pack(fill="x")
        actions = tk.Frame(window,bg=self.colors["surface"])
        actions.pack(fill="x",pady=(8,0))
        ttk.Button(actions,text="Stop",style="Mac.TButton",command=lambda:(self.app.stop(),window.destroy())).pack(side="left")
        ttk.Button(actions,text="Settings",style="Mac.TButton",command=lambda:(self.app.show_settings_from_tray(),self.app.settings_shell.show("Schedule"),window.destroy())).pack(side="right")
        window.geometry(f"380x110+{max(0,self.app.root.winfo_screenwidth()-400)}+30")
        window.after(12000,window.destroy)


def page(app, colors):
    from weekly_schedule_ui import page as workday_page
    workday_page(app, colors)
    notice = app.preferences.get("SCHEDULE", "timezone_notice", "")
    if notice:
        app.show_hint(notice)
        app.preferences.set("SCHEDULE", "timezone_notice", "")
