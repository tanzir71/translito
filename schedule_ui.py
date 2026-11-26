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
        self.scheduler = Scheduler(clock=lambda:datetime.now(timezone.utc), running=lambda:app.transcriber is not None or app.model_setup_busy,
            start_listen=self.start_listen, stop=app.stop, app_has_audio=self.app_has_audio, notice=self.toast,
            confirm=lambda event:messagebox.askyesno("Scheduled meeting", "Start listening for this meeting?", parent=app.root))
        self.variables = {}
        for key, default in (("enabled", False), ("source", "weekly"), ("weekly_times", "[]"), ("lead_seconds", 60),
            ("stop_rule", "end"), ("silence_seconds", 300), ("wait_for_app_audio", True), ("ask_before_start", False),
            ("only_with_call_link", False), ("timezone", "UTC")):
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
                    self.events = weekly_meetings(json.loads(values["weekly_times"].get()), now-timedelta(days=1), now+timedelta(days=7), default_timezone=values["timezone"].get())
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
            self.scheduler.tick(self.events, **{key:var.get() for key,var in values.items() if key in {
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
    from engine_ui import field, heading
    from ui_widgets import Switch
    controller, parent = app.schedule_controller, app.settings_shell.contents["Schedule"]
    variables = controller.variables
    heading(parent,"Schedule","Start listening and show subtitles when meetings begin. Translito must remain running in the tray.",colors)
    row = tk.Frame(parent,bg=colors["bg"])
    row.pack(fill="x",pady=8)
    tk.Label(row,text="Start automatically for meetings",bg=colors["bg"],fg=colors["text"]).pack(side="left")
    Switch(row,variables["enabled"],colors).pack(side="right")
    field(parent,"Meeting times come from",variables["source"],colors,("ical","weekly"))
    link = tk.StringVar()
    entry = field(parent,"Private calendar link (stored securely; press Enter)",link,colors)
    entry.configure(show="•")
    status = tk.StringVar(value="The calendar link is kept in Credential Manager. Open at login keeps scheduling available.")
    def connect(_event=None):
        if app.preview_mode:
            status.set("Preview: no credentials are read or saved.")
            return
        if link.get():
            try:
                controller.calendar_feed().connect(link.get())
                link.set("")
                controller.next_refresh = None
                status.set("Calendar link stored securely. Times refresh every 15 minutes.")
            except Exception:
                status.set("Calendar connection failed. Use a read-only HTTPS iCal link.")
    entry.bind("<Return>",connect)
    entry.bind("<FocusOut>",connect)
    field(parent,"Time zone for weekly times",variables["timezone"],colors)
    days = ("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")
    day, start, end = tk.StringVar(value=days[0]), tk.StringVar(value="15:00"), tk.StringVar(value="16:00")
    field(parent,"Day",day,colors,days)
    field(parent,"Start (24-hour HH:MM)",start,colors)
    field(parent,"End (24-hour HH:MM)",end,colors)
    listing = tk.Listbox(parent,bg=colors["field"],fg=colors["text"],height=3,relief="flat",bd=0)
    listing.pack(fill="x",pady=8)
    def render(*_):
        listing.delete(0,"end")
        try:
            for item in json.loads(variables["weekly_times"].get()):
                listing.insert("end",f"{days[item['weekday']]} {item['start']} – {item['end']} · {item.get('timezone','UTC')}")
        except (ValueError,KeyError,TypeError):
            status.set("Weekly times could not be read. Existing settings were preserved.")
    def add():
        try:
            items = json.loads(variables["weekly_times"].get())
            value = dict(weekday=days.index(day.get()),start=start.get(),end=end.get(),timezone=variables["timezone"].get())
            weekly_meetings([value],datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(days=7))
            variables["weekly_times"].set(json.dumps([*items,value]))
        except (ValueError,KeyError,TypeError):
            status.set("Use a valid IANA time zone and HH:MM times.")
    def remove():
        if listing.curselection():
            items = json.loads(variables["weekly_times"].get())
            items.pop(listing.curselection()[0])
            variables["weekly_times"].set(json.dumps(items))
    buttons = tk.Frame(parent,bg=colors["bg"])
    buttons.pack(fill="x")
    ttk.Button(buttons,text="Add weekly time",style="Mac.TButton",command=add).pack(side="left")
    ttk.Button(buttons,text="Remove selected",style="Mac.TButton",command=remove).pack(side="left",padx=8)
    variables["weekly_times"].trace_add("write",render)
    render()
    field(parent,"Start this many seconds before the meeting",variables["lead_seconds"],colors,(0,30,60,120,300))
    field(parent,"Stop",variables["stop_rule"],colors,("end","silence"))
    field(parent,"Stop after silence (seconds)",variables["silence_seconds"],colors,(60,180,300,600))
    for key,label in (("wait_for_app_audio","Wait until the default meeting app plays audio"),("ask_before_start","Ask before each start"),("only_with_call_link","Only events containing a call link")):
        tk.Checkbutton(parent,text=label,variable=variables[key],**{**app._checkbutton_options(),"bg":colors["bg"]}).pack(anchor="w",pady=5)
    tk.Label(parent,textvariable=status,bg=colors["bg"],fg=colors["tertiary"],wraplength=550,justify="left",anchor="w").pack(fill="x",pady=12)
