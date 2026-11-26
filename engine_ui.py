"""Engine and cost pages using the Figma spacing and existing dark controls."""
from decimal import Decimal
import tkinter as tk
from tkinter import ttk

from engines.registry import provider_factories
from engines.settings import budget, load_engine_settings
from settings_schema import money
from engines.usage import UsageLedger


def initialize(app):
    state = app.preferences
    settings = load_engine_settings(state.path)
    for name, section, key, default in (
        ("engine_choice", "ENGINES", "engine_choice", settings.engine_choice or ("local" if settings.profile == "offline" else "free")),
        ("monthly_budget", "ENGINES", "monthly_cap_usd", str(settings.monthly_cap)),
        ("budget_fallback", "ENGINES", "fallback_on_budget", settings.fallback_on_budget),
        ("budget_warning", "ENGINES", "budget_warn_percent", str(settings.budget_warn_percent)),
        ("engine_scope", "UI", "engine_scope", "all"),
        ("skip_non_speech", "COSTGUARD", "skip_non_speech", True),
        ("skip_other_languages", "COSTGUARD", "skip_other_languages", True),
        ("close_idle", "COSTGUARD", "close_idle_seconds", "8")):
        variable = tk.BooleanVar(app.root) if isinstance(default, bool) else tk.StringVar(app.root)
        setattr(app, name + "_var", state.bind(variable, section, key, default))
    app.engine_default_vars = {}
    for key, value in settings.resolve(*pair(app)).items():
        variable = tk.StringVar(app.root, value=value)
        variable.trace_add("write", lambda *_, k=key, v=variable: save_default(app, k, v.get()))
        app.engine_default_vars[key] = variable
    def choice_changed(*_):
        if app._initializing:
            return
        choice = app.engine_choice_var.get()
        app.engine_profile_var.set({"cloud": "Custom", "local": "Offline (private)", "free": "Free (recommended)"}[choice])
        app.change_engine_profile()
        if choice == "cloud" and not app.engine_default_vars["default_asr_provider"].get():
            app.engine_default_vars["default_asr_provider"].set("soniox")
        if choice == "cloud" and safe_budget(app.monthly_budget_var.get()) == 0:
            app.show_hint("Set a monthly budget in Cost & usage before using paid cloud engines.")
    app.engine_choice_var.trace_add("write", choice_changed)
    app.engine_scope_var.trace_add("write", lambda *_: restore_scope(app))
    for variable in (app.monthly_budget_var, app.budget_fallback_var, app.budget_warning_var):
        variable.trace_add("write", lambda *_: apply_budget(app))


def pair(app):
    return tuple(app.language_entry_by_name(v.get())[2] for v in (app.listen_source_var, app.listen_target_var))


def save_default(app, key, value):
    if getattr(app, "_loading_engine_scope", False):
        return
    source, target = pair(app)
    key = key if app.engine_scope_var.get() == "all" else f"pair_{source}_{target}_{key.removeprefix('default_')}"
    app.preferences.set("ENGINES", key, value)
    refresh_measurements(app)


def restore_scope(app):
    app._loading_engine_scope = True
    settings = load_engine_settings(app.preferences.path)
    for key, variable in app.engine_default_vars.items():
        variable.set(getattr(settings, key) if app.engine_scope_var.get() == "all" else settings.resolve(*pair(app))[key])
    app._loading_engine_scope = False
    refresh_provider_choices(app)


def refresh_provider_choices(app):
    factories = provider_factories()
    source, target = pair(app)
    reasons = []
    for kind, widget in getattr(app, "engine_provider_widgets", {}).items():
        candidates = [f for f in factories if f.kind == kind or (kind == "asr" and f.kind == "live")]
        widget.configure(values=[getattr(widget, "display_labels", {}).get(name, name) for name in ["local"] + [f.name for f in candidates]])
        chosen = app.engine_default_vars[f"default_{kind}_provider"].get()
        factory = next((f for f in candidates if f.name == chosen), None)
        if factory and factory.unavailable_reason(source,target):
            reasons.append(f"{chosen}: {factory.unavailable_reason(source,target)} Choose a supported provider.")
    if hasattr(app, "engine_support_var"):
        app.engine_support_var.set(" ".join(reasons))


def field(parent, label, variable, colors, values=None):
    frame = tk.Frame(parent, bg=colors["bg"])
    frame.pack(fill="x", pady=5)
    tk.Label(frame, text=label, bg=colors["bg"], fg=colors["secondary"], anchor="w", font=("Segoe UI", 8)).pack(fill="x", pady=(0, 4))
    display = variable
    labels = getattr(getattr(variable, "setting", None), "labels", {})
    if values is not None and label.casefold().endswith(" provider"):
        labels = {"local": "On this PC", **{f.name: f.title for f in provider_factories()}}
    if values is not None and labels:
        display = tk.StringVar(parent, value=labels.get(variable.get(), variable.get()))
        syncing = [False]
        def from_store(*_):
            if not syncing[0]:
                syncing[0] = True
                display.set(labels.get(variable.get(), variable.get()))
                syncing[0] = False
        def to_store(*_):
            if not syncing[0]:
                syncing[0] = True
                variable.set(next((key for key,label in labels.items() if label == display.get()), display.get()))
                syncing[0] = False
        variable.trace_add("write", from_store)
        display.trace_add("write", to_store)
        values = [labels.get(value, value) for value in values]
    widget = (ttk.Combobox(frame, textvariable=display, values=values, state="readonly", style="Dark.TCombobox")
              if values is not None else ttk.Entry(frame, textvariable=variable, style="Dark.TEntry"))
    widget.display_labels = labels
    widget.pack(fill="x")
    owner = getattr(variable, "settings_owner", None)
    if owner and not variable.setting.live:
        note = tk.Label(frame, bg=colors["bg"], fg=colors["orange"], anchor="w", font=("Segoe UI", 8))
        note.pack(fill="x")
        def next_session(*_):
            if note.winfo_exists():
                note.configure(text="Applies when you start the next session" if owner.transcriber is not None else "")
        variable.trace_add("write", next_session)
        next_session()
    if hasattr(variable, "validation_error"):
        tk.Label(frame, textvariable=variable.validation_error, bg=colors["bg"], fg=colors["red"],
                 anchor="w", font=("Segoe UI", 8)).pack(fill="x")
        widget.bind("<FocusOut>", lambda event: variable.save_now())
        widget.bind("<Return>", lambda event: variable.save_now())
        if values is not None:
            widget.bind("<<ComboboxSelected>>", lambda event: variable.save_now())
    return widget


def heading(parent, title, description, colors):
    tk.Label(parent, text=title, bg=colors["bg"], fg=colors["text"], font=("Segoe UI Semibold", 13), anchor="w").pack(fill="x")
    tk.Label(parent, text=description, bg=colors["bg"], fg=colors["secondary"], font=("Segoe UI", 9),
             wraplength=560, justify="left", anchor="w").pack(fill="x", pady=(4, 16))


def pages(app, colors):
    engine = app.settings_shell.contents["Engine"]
    cost = app.settings_shell.contents["Cost & usage"]
    heading(engine, "Engine", "Where speech is recognized and translated. Prices are per hour of speech sent.", colors)
    app.engine_cards, app.engine_card_descriptions = [], {}
    chosen = load_engine_settings(app.preferences.path).resolve(*pair(app))["default_asr_provider"] or "soniox"
    factory = next((f for f in provider_factories() if f.name == chosen), None)
    rate = factory.display_hourly_rate if factory else Decimal(".18")
    for value, title, description, price in (
        ("cloud", "Cloud, pay as you go", "Most accurate. Sends only speech in your languages.", f"${rate:.2f} per hour"),
        ("local", "On this PC", "Free and private. Nothing leaves this computer.", "Free · no limit"),
        ("free", "Free cloud allowances", "Free tiers with limits. Some providers reuse your data.", "Free · limited")):
        card = tk.Frame(engine, bg=colors["surface"], highlightthickness=1, highlightbackground=colors["border"], padx=12, pady=10)
        card.pack(fill="x", pady=(0, 8))
        tk.Radiobutton(card, text=title, variable=app.engine_choice_var, value=value, bg=colors["surface"], fg=colors["text"],
            selectcolor=colors["field"], activebackground=colors["surface"], activeforeground=colors["text"],
            font=("Segoe UI", 10), anchor="w").pack(side="left")
        tk.Label(card, text=price, bg=colors["surface"], fg=colors["text"], font=("Segoe UI", 9)).pack(side="right")
        app.engine_cards.append((value, card))
        description_var = tk.StringVar(app.root, value=description)
        app.engine_card_descriptions[value] = description_var
        tk.Label(engine, textvariable=description_var, bg=colors["bg"], fg=colors["secondary"],
                 anchor="w", wraplength=520, font=("Segoe UI", 8)).pack(fill="x", pady=(0, 6))
    cloud = tk.Frame(engine, bg=colors["bg"])
    cloud.pack(fill="x", pady=10)
    from cloud_ui import provider_page
    provider_page(app, cloud, colors)
    free = tk.Frame(engine, bg=colors["bg"])
    tk.Label(free, text="Connect a free account and review its data-use terms in Advanced.", bg=colors["bg"], fg=colors["secondary"], wraplength=520).pack(anchor="w")
    ttk.Button(free, text="Connect a free provider", style="Mac.TButton", command=app.open_provider_settings).pack(anchor="w", pady=8)
    advanced_button = ttk.Button(engine, text="Advanced ▸", style="Mac.TButton")
    advanced_button.pack(fill="x", pady=8)
    advanced = tk.Frame(engine, bg=colors["bg"])
    advanced_button.configure(command=lambda: advanced.pack_forget() if advanced.winfo_manager() else advanced.pack(fill="x", after=advanced_button))
    ttk.Button(advanced, text="Provider limits, keys and data-use terms", style="Mac.TButton", command=app.open_provider_settings).pack(anchor="w", pady=8)
    factories = provider_factories()
    app.engine_provider_widgets = {}
    for kind, label in (("asr", "Recognition"), ("mt", "Translation")):
        providers = ["local"] + [f.name for f in factories if f.kind == kind or (kind == "asr" and f.kind == "live")]
        variable = app.engine_default_vars[f"default_{kind}_provider"]
        app.engine_provider_widgets[kind] = field(advanced, label + " provider", variable, colors, providers)
        model = field(advanced, label + " model", app.engine_default_vars[f"default_{kind}_model"], colors, [])
        def refresh(*_, v=variable, m=model, k=kind):
            if m.winfo_exists():
                factory = next((f for f in factories if f.name == v.get()), None)
                from gui import WHISPER_MODELS
                choices = factory.models if factory else tuple(WHISPER_MODELS) if k == "asr" else ("automatic", "opus", "translategemma")
                m.configure(values=choices)
        variable.trace_add("write", refresh)
        refresh()
    app.engine_support_var = tk.StringVar(app.root)
    tk.Label(advanced, textvariable=app.engine_support_var, bg=colors["bg"], fg=colors["orange"], wraplength=520).pack(fill="x")
    field(advanced, "Use these defaults for", app.engine_scope_var, colors, ("all", "pair"))
    def selected(*_):
        choice = app.engine_choice_var.get()
        for value, card in app.engine_cards:
            if card.winfo_exists():
                card.configure(highlightbackground=colors["blue"] if value == choice else colors["border"])
        if choice == "cloud":
            cloud.pack(fill="x", before=advanced_button)
            free.pack_forget()
        elif choice == "free":
            cloud.pack_forget()
            free.pack(fill="x", before=advanced_button)
        else:
            cloud.pack_forget()
            free.pack_forget()
        refresh_engine_status(app)
    app.engine_choice_var.trace_add("write", selected)
    selected()
    heading(cost, "Cost & usage", "Figures are estimates or conservative reservations until billing is known.", colors)
    app.cost_summary_var = tk.StringVar(value="This month $0.00 · speech sent 0 min of 0 min captured")
    tk.Label(cost, textvariable=app.cost_summary_var, bg=colors["bg"], fg=colors["text"], wraplength=540, justify="left").pack(fill="x", pady=12)
    ttk.Button(cost, text="Change the monthly budget in Engine", style="Mac.TButton", command=lambda: app.settings_shell.show("Engine")).pack(anchor="w")
    field(cost, "Warn at", app.budget_warning_var, colors, ("50", "75", "80", "90", "100"))
    for title, variable in (("Skip silence, music and noise", app.skip_non_speech_var), ("Skip speech outside the selected languages", app.skip_other_languages_var)):
        tk.Checkbutton(cost, text=title, variable=variable, **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=6)
    field(cost, "Close idle connections after seconds (8–10)", app.close_idle_var, colors, ("8", "9", "10"))
    app.provider_totals_var = tk.StringVar()
    tk.Label(cost, textvariable=app.provider_totals_var, bg=colors["bg"], fg=colors["secondary"], anchor="w", justify="left").pack(fill="x", pady=16)
    refresh_provider_choices(app)
    refresh_measurements(app)
    refresh_usage(app)


def safe_budget(value):
    try:
        return budget(money(value))
    except ValueError:
        return Decimal(0)


def refresh_measurements(app):
    if hasattr(app, "empty_measurements_var"):
        app.empty_measurements_var.set("On this PC, meeting audio and text stay private. Connect cloud for faster subtitles; list prices apply only to speech sent.")
    if hasattr(app, "engine_label"):
        refresh_engine_status(app)


def refresh_engine_status(app, failure=""):
    from engines.engine_status import engine_status
    settings = load_engine_settings(app.preferences.path)
    if app.preview_mode:
        from dataclasses import replace
        settings = replace(settings, engine_choice=app.engine_choice_var.get())
    status = engine_status(settings, pair(app), block_all=app.offline_only_var.get(),
        usage=None if app.preview_mode else UsageLedger().snapshot(), failure=failure)
    app.engine_var.set(status.text)
    app.engine_label.configure(fg=__import__("gui").COLORS["orange" if status.reason else "secondary"], cursor="hand2")
    app.engine_label.bind("<Button-1>", lambda event: app.open_cloud_setup())
    return status


def apply_budget(app):
    """Update active reservation policies without rebuilding or reading keys."""
    if app.preview_mode or app._initializing:
        return
    transcriber = app.transcriber
    if transcriber is None:
        return
    cap = safe_budget(app.monthly_budget_var.get())
    fallback = app.budget_fallback_var.get()
    warning = int(app.budget_warning_var.get())
    pipeline = getattr(transcriber, "conversation_pipeline", None)
    fallback_pipeline = getattr(pipeline, "fallback", pipeline)
    for candidate in (getattr(transcriber, "recognizer", None), getattr(transcriber, "translator_engine", None),
                      getattr(transcriber, "recognition_router", None), getattr(transcriber, "translation_router", None),
                      getattr(fallback_pipeline, "recognizer", None), getattr(fallback_pipeline, "translator", None)):
        router = getattr(candidate, "router", candidate)
        if hasattr(router, "total_monthly_cap"):
            router.total_monthly_cap, router.fallback_on_budget, router.budget_warn_percent = cap, fallback, warning
    interpreter = getattr(pipeline, "interpreter", None)
    guard = getattr(interpreter, "guard", None)
    if guard:
        guard.total_monthly_cap, guard.fallback_on_budget, guard.budget_warn_percent = cap, fallback, warning
        spent = sum(Decimal(v["estimated_usd"]) for v in guard.ledger.snapshot()["providers"].values())
        if cap <= spent and not guard.paused:
            guard.paused = True
            interpreter.emit("budget", {"action": fallback, "message": "Monthly budget reached."})
            if fallback == "local":
                interpreter.emit("fallback", "Monthly budget reached. Continuing on this PC.")


def refresh_usage(app):
    if app.preview_mode:
        return
    try:
        snapshot = UsageLedger().snapshot()
        providers = snapshot["providers"]
        spent = sum((Decimal(p["estimated_usd"]) for p in providers.values()), Decimal(0))
        sessions = dict(snapshot.get("sessions", {}))
        interpreter = getattr(getattr(app.transcriber, "conversation_pipeline", None), "interpreter", None)
        guard = getattr(interpreter, "guard", None)
        if guard:
            sessions[guard.session_id] = {"captured_seconds": guard.captured_seconds, "sent_seconds": guard.sent_seconds}
        sessions = sessions.values()
        captured = sum(s.get("captured_seconds", 0) for s in sessions)
        sent = sum(s.get("sent_seconds", 0) for s in sessions)
        if hasattr(app, "cost_summary_var"):
            average = f" · ${spent * 3600 / Decimal(str(captured)):.3f}/meeting h, estimated" if captured else " · Average: not measured"
            app.cost_summary_var.set(f"This month ${spent:.2f} of ${safe_budget(app.monthly_budget_var.get()):.2f} · {sent/60:.1f} of {captured/60:.1f} min sent" + average + f"\n{max(0,captured-sent)/60:.1f} min kept on this PC by the guard.")
            app.provider_totals_var.set("\n".join(f"{name}   ${Decimal(p['estimated_usd']):.4f} estimated" for name, p in providers.items()) or "No cloud usage recorded.")
        app.month_cost_var.set(f"This month ${spent:.2f} / ${safe_budget(app.monthly_budget_var.get()):.2f}")
        if guard:
            baseline = getattr(app,"session_cost_baseline",spent)
            app.session_cost_var.set(f"Session ${max(Decimal(0),spent-baseline):.3f} · {guard.sent_seconds/60:.1f}/{guard.captured_seconds/60:.1f} min")
    except (ValueError, OSError, RuntimeError):
        app.month_cost_var.set("This month unavailable")
