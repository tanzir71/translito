"""Workday chips and editable hours in the Schedule settings page."""
from ui_scale import px, scaled_geometry
from datetime import datetime, timedelta, timezone
import json
import tkinter as tk
from tkinter import ttk
from zoneinfo import available_timezones

from engines.weekly_schedule import DAYS, PRESETS, day_order, normalize_time, summary, validate_blocks


def page(app, colors):
    from engine_ui import field, heading
    from ui_widgets import Switch
    parent, controller = app.settings_shell.contents["Schedule"], app.schedule_controller
    values = controller.variables
    heading(parent, "Schedule", "Start listening and show subtitles on their own at your meeting times.", colors)
    def toggle(label, variable, command=None):
        row = tk.Frame(parent, bg=colors["bg"])
        row.pack(fill="x", pady=px(7))
        tk.Label(row, text=label, bg=colors["bg"], fg=colors["text"]).pack(side="left")
        switch = Switch(row, variable, colors, command=command)
        switch.pack(side="right")
        return switch
    toggle("Start automatically for meetings", values["enabled"])
    toggle("Open Translito when Windows starts", app.login_var, app.toggle_login)
    login_note = tk.StringVar(parent)
    tk.Label(parent, textvariable=login_note, bg=colors["bg"], fg=colors["secondary"], wraplength=px(540), justify="left", anchor="w").pack(fill="x", pady=px((0, 12)))
    def login_changed(*_):
        if parent.winfo_exists():
            login_note.set("The schedule only runs while Translito is open in the tray." +
                (" Turn this on so the schedule keeps working after a restart." if values["enabled"].get() and not app.login_var.get() else ""))
    app.login_var.trace_add("write", login_changed)
    values["enabled"].trace_add("write", login_changed)
    login_changed()
    source_cards, expansions = {}, {}
    for source, title, copy in (("ical", "A calendar link", "Paste the private iCal link from Google Calendar, Outlook or iCloud."),
                                 ("weekly", "Fixed weekly times", "The same hours on the days you choose.")):
        card = tk.Frame(parent, bg=colors["surface"], padx=px(12), pady=px(12), highlightthickness=px(1), highlightbackground=colors["border"])
        card.pack(fill="x", pady=px(6))
        tk.Radiobutton(card, text=title, variable=values["source"], value=source, bg=colors["surface"], fg=colors["text"],
                       selectcolor=colors["field"], activebackground=colors["surface"], activeforeground=colors["text"]).pack(anchor="w")
        tk.Label(card, text=copy, bg=colors["surface"], fg=colors["secondary"], wraplength=px(510), justify="left").pack(anchor="w", padx=px(20))
        expansions[source] = tk.Frame(card, bg=colors["surface"])
        source_cards[source] = card
    calendar = expansions["ical"]
    calendar_key, calendar_status = tk.StringVar(parent), tk.StringVar(parent)
    calendar_entry = field(calendar, "Private calendar link (stored securely; press Enter)", calendar_key, colors)
    calendar_entry.configure(show="•")
    def connect_calendar(event=None):
        if app.preview_mode:
            calendar_status.set("Preview only: no key is saved and no calendar is contacted.")
            return
        try:
            controller.calendar_feed().connect(calendar_key.get())
            calendar_key.set("")
            calendar_status.set("Calendar link saved securely")
            controller.next_refresh = None
        except Exception:
            calendar_status.set("Couldn't save the calendar link. Use an HTTPS read-only calendar link.")
    calendar_entry.bind("<Return>", connect_calendar)
    ttk.Button(calendar, text="Connect calendar", style="Mac.TButton", command=connect_calendar).pack(anchor="e", pady=px(6))
    tk.Label(calendar, textvariable=calendar_status, bg=colors["surface"], fg=colors["secondary"], wraplength=px(500)).pack(fill="x")
    weekly = expansions["weekly"]
    block_host = tk.Frame(weekly, bg=colors["surface"])
    block_host.pack(fill="x", pady=px(10))
    error = tk.StringVar(parent)
    tk.Label(weekly, textvariable=error, bg=colors["surface"], fg=colors["red"], wraplength=px(510), justify="left").pack(fill="x")
    blocks = json.loads(values["weekly_blocks"].get())
    views = []
    def save():
        try:
            cleaned = validate_blocks(blocks)
        except (ValueError, KeyError) as invalid:
            error.set(str(invalid))
            return False
        error.set("")
        values["weekly_blocks"].set(json.dumps(cleaned))
        return True
    def zone_picker(index):
        from quality_settings import _window
        from gui import center_window
        window = _window(app, "Choose a time zone", colors, center_window, 440, 420)
        body = tk.Frame(window, bg=colors["bg"], padx=px(18), pady=px(18))
        body.pack(fill="both", expand=True)
        query = tk.StringVar(window)
        entry = field(body, "Search time zones", query, colors)
        listing = tk.Listbox(body, height=px(13, chars=True), exportselection=False)
        listing.pack(fill="both", expand=True, pady=px(8))
        zones = sorted(available_timezones())
        def search(*_):
            listing.delete(0, "end")
            for zone in zones:
                if query.get().casefold() in zone.casefold():
                    listing.insert("end", zone)
        def choose():
            selection = listing.curselection()
            if selection:
                blocks[index]["timezone"] = listing.get(selection[0])
                if save():
                    render()
                    window.destroy()
        query.trace_add("write", search)
        search()
        listing.bind("<Double-1>", lambda event: choose())
        ttk.Button(body, text="Use this time zone", style="Primary.TButton", command=choose).pack(anchor="e")
        entry.focus_set()
    def render():
        for child in block_host.winfo_children():
            child.destroy()
        views.clear()
        for index, block in enumerate(blocks):
            panel = tk.Frame(block_host, bg=colors["surface"], pady=px(8))
            panel.pack(fill="x")
            presets = tk.Frame(panel, bg=colors["surface"])
            presets.pack(fill="x")
            tk.Label(presets, text="Days", bg=colors["surface"], fg=colors["secondary"]).pack(side="left")
            used = {day: i for i,b in enumerate(blocks) if i != index for day in b["days"]}
            def preset(days, i=index, occupied=used):
                chosen = [d for d in days if d not in occupied]
                if not chosen:
                    error.set("Those days already have hours in another block")
                    return
                blocks[i]["days"] = chosen
                if save():
                    render()
            for title, days in PRESETS.items():
                ttk.Button(presets, text=title, style="Mac.TButton", command=lambda ds=days, fn=preset: fn(ds)).pack(side="right", padx=px(2))
            chips = tk.Frame(panel, bg=colors["surface"])
            chips.pack(fill="x", pady=px(6))
            day_buttons = {}
            for day in day_order():
                chosen = day in block["days"]
                def toggle_day(d=day, i=index):
                    selected = blocks[i]["days"]
                    if d in selected and len(selected) == 1:
                        error.set("Keep at least one day selected")
                        return
                    selected.remove(d) if d in selected else selected.append(d)
                    if save():
                        render()
                chip = tk.Button(chips, text=DAYS[day][:3], command=toggle_day, bg=colors["blue_bg"] if chosen else colors["surface"],
                    fg=colors["text"] if chosen else colors["secondary"], activebackground=colors["field"], activeforeground=colors["text"],
                    relief="flat", highlightthickness=px(1), highlightbackground=colors["blue"] if chosen else colors["border"], padx=px(8), pady=px(6),
                    state="disabled" if day in used else "normal")
                chip.pack(side="left", expand=True, fill="x", padx=px(2))
                chip.tooltip = f"Block {used[day]+1} already uses {DAYS[day]}" if day in used else ""
                if chip.tooltip:
                    def enter(event, button=chip):
                        tip = tk.Toplevel(button)
                        tip.overrideredirect(True)
                        tk.Label(tip, text=button.tooltip, bg=colors["field"], fg=colors["text"], padx=px(8), pady=px(5)).pack()
                        tip.geometry(f"+{button.winfo_rootx()}+{button.winfo_rooty()+button.winfo_height()+px(4)}")
                        button.tip = tip
                    def leave(event, button=chip):
                        if getattr(button, "tip", None):
                            button.tip.destroy()
                            button.tip = None
                    chip.bind("<Enter>", enter)
                    chip.bind("<Leave>", leave)
                day_buttons[day] = chip
            times = tk.Frame(panel, bg=colors["surface"])
            times.pack(fill="x", pady=px(6))
            variables = {}
            for key, title in (("start", "From"), ("end", "To")):
                column = tk.Frame(times, bg=colors["surface"])
                column.pack(side="left", padx=px((0, 12)))
                tk.Label(column, text=title, bg=colors["surface"], fg=colors["secondary"]).pack(anchor="w")
                var = tk.StringVar(parent, value=block[key])
                combo = ttk.Combobox(column, textvariable=var, values=[f"{h:02d}:{m:02d}" for h in range(24) for m in range(0,60,15)], width=px(9, chars=True), style="Dark.TCombobox")
                combo.pack()
                def changed(event=None, v=var, k=key, i=index):
                    try:
                        normalized = normalize_time(v.get())
                    except ValueError as invalid:
                        error.set(str(invalid))
                        return
                    if i >= len(blocks):
                        return
                    blocks[i][k] = normalized
                    if save():
                        if v.get() != normalized:
                            v.set(normalized)
                        views[i]["summary"].set(summary(blocks[i]))
                pending = [None]
                def debounce(*_, v=var, fn=changed, waiting=pending):
                    if waiting[0]:
                        parent.after_cancel(waiting[0])
                    waiting[0] = parent.after(400, fn)
                var.trace_add("write", debounce)
                combo.bind("<<ComboboxSelected>>", changed)
                combo.bind("<Return>", changed)
                combo.bind("<FocusOut>", changed)
                variables[key] = (var, combo)
            ttk.Button(times, text="Your PC's time zone\n"+block["timezone"]+" · change", style="Mac.TButton", command=lambda i=index: zone_picker(i)).pack(side="left", fill="x", expand=True)
            summary_var = tk.StringVar(parent, value=summary(block))
            tk.Label(panel, textvariable=summary_var, bg=colors["surface"], fg=colors["green"], wraplength=px(510), justify="left", anchor="w").pack(fill="x", pady=px(6))
            if index:
                def remove(i=index):
                    blocks.pop(i)
                    if save():
                        render()
                ttk.Button(panel, text="Remove", style="Mac.TButton", command=remove).pack(anchor="e")
            views.append({"days": day_buttons, "times": variables, "summary": summary_var, "preset": preset})
        app.schedule_block_views = views
    def add():
        used = {d for b in blocks for d in b["days"]}
        remaining = sorted(set(range(7))-used)
        if not remaining:
            error.set("All days already have hours. Remove a day from another block first.")
            return
        blocks.append(dict(days=remaining, start="09:30", end="18:00", timezone=values["timezone"].get(), title="Different hours"))
        if save():
            render()
    ttk.Button(weekly, text="+ Different hours on some days", style="Mac.TButton", command=add).pack(anchor="w", pady=px(6))
    app.schedule_add_block = add
    app.schedule_error_var = error
    render()
    def source_changed(*_):
        if not parent.winfo_exists():
            return
        for name, expansion in expansions.items():
            source_cards[name].configure(highlightbackground=colors["blue"] if values["source"].get() == name else colors["border"])
            expansion.pack(fill="x", padx=px(20), pady=px(6)) if values["source"].get() == name else expansion.pack_forget()
    values["source"].trace_add("write", source_changed)
    source_changed()
    field(parent, "Start", values["lead_seconds"], colors, (0,60,120,300))
    stop = tk.StringVar(parent, value="At the end time" if values["stop_rule"].get() == "end" else
                        "After 10 min of silence" if values["silence_seconds"].get() == 600 else "After 5 min of silence")
    stop_combo = field(parent, "Stop", stop, colors, ("At the end time", "After 5 min of silence", "After 10 min of silence"))
    def stop_changed(*_):
        values["stop_rule"].set("end" if stop.get() == "At the end time" else "silence")
        if "silence" in stop.get():
            values["silence_seconds"].set(600 if "10" in stop.get() else 300)
    stop_combo.bind("<<ComboboxSelected>>", stop_changed)
    for title, key in (("Wait until the meeting app plays audio, so an empty meeting costs nothing", "wait_for_app_audio"), ("Ask me before each start", "ask_before_start")):
        tk.Checkbutton(parent, text=title, variable=values[key], **{**app._checkbutton_options(), "bg": colors["bg"]}, wraplength=px(520), justify="left").pack(anchor="w", pady=px(6))
    tk.Label(parent, text="Coming up", bg=colors["bg"], fg=colors["text"], font=("Segoe UI Semibold", 10)).pack(anchor="w", pady=px(12))
    coming = tk.Frame(parent, bg=colors["bg"])
    coming.pack(fill="x")
    def refresh_coming():
        if not parent.winfo_exists():
            return
        for child in coming.winfo_children():
            child.destroy()
        now = datetime.now(timezone.utc)
        if values["source"].get() == "weekly":
            from engines.schedule import weekly_meetings
            events = weekly_meetings(json.loads(values["weekly_blocks"].get()), now, now+timedelta(days=8))
        else:
            events = controller.events
        skipped = {item["id"] for item in json.loads(values["skipped"].get())}
        for event in [e for e in events if e.end > now][:3]:
            row = tk.Frame(coming, bg=colors["bg"])
            row.pack(fill="x", pady=px(6))
            text = event.start.astimezone().strftime("%a %H:%M") + " – " + event.end.astimezone().strftime("%H:%M") + "  " + event.title
            tk.Label(row, text=text, bg=colors["bg"], fg=colors["secondary"], wraplength=px(450)).pack(side="left")
            enabled = tk.BooleanVar(parent, value=event.id not in skipped)
            def skip(v=enabled, e=event):
                items = [item for item in json.loads(values["skipped"].get()) if item["id"] != e.id]
                if not v.get():
                    items.append({"id":e.id,"end":e.end.isoformat()})
                values["skipped"].set(json.dumps(items))
            Switch(row, enabled, colors, command=skip).pack(side="right")
        parent.after(30000, refresh_coming)
    refresh_coming()
    tk.Label(parent, text="Scheduled sessions count toward your monthly budget. With Wait until the meeting app plays audio, a quiet day costs nothing.",
             bg=colors["bg"], fg=colors["tertiary"], wraplength=px(540), justify="left").pack(fill="x", pady=px(12))
