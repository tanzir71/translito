"""Engine and cost pages using the Figma spacing and existing dark controls."""
from decimal import Decimal
import tkinter as tk
from tkinter import ttk

from engines.registry import provider_factories
from engines.settings import budget, load_engine_settings
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
        widget.configure(values=["local"] + [f.name for f in candidates if not f.unavailable_reason(source,target)])
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
    widget = (ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", style="Dark.TCombobox")
              if values is not None else ttk.Entry(frame, textvariable=variable, style="Dark.TEntry"))
    widget.pack(fill="x")
    return widget


def heading(parent, title, description, colors):
    tk.Label(parent, text=title, bg=colors["bg"], fg=colors["text"], font=("Segoe UI Semibold", 13), anchor="w").pack(fill="x")
    tk.Label(parent, text=description, bg=colors["bg"], fg=colors["secondary"], font=("Segoe UI", 9),
             wraplength=560, justify="left", anchor="w").pack(fill="x", pady=(4, 16))


def pages(app, colors):
    engine = app.settings_shell.contents["Engine"]
    cost = app.settings_shell.contents["Cost & usage"]
    heading(engine, "Engine", "Where speech is recognized and translated. Run a check for measured figures for your pair.", colors)
    app.engine_cards = []
    app.engine_card_descriptions = {}
    for value, title, description in (
        ("cloud", "Cloud, pay as you go", "Sends gated speech. Delay and accuracy: not measured. Cost: list estimate; see provider."),
        ("local", "On this PC", "Free and private. Delay and accuracy: run a check on this PC."),
        ("free", "Free cloud allowances", "Tested free accounts, then local fallback. Delay and accuracy: not measured.")):
        card = tk.Frame(engine, bg=colors["bg"], highlightthickness=1, highlightbackground=colors["border"], padx=12, pady=10, takefocus=True)
        card.pack(fill="x", pady=(0, 8))
        radio = tk.Radiobutton(card, text=title, variable=app.engine_choice_var, value=value, bg=colors["bg"], fg=colors["text"],
            selectcolor=colors["field"], activebackground=colors["bg"], activeforeground=colors["text"], font=("Segoe UI", 10), anchor="w")
        radio.pack(fill="x")
        description_var = tk.StringVar(app.root, value=description)
        app.engine_card_descriptions[value] = description_var
        tk.Label(card, textvariable=description_var, bg=colors["bg"], fg=colors["tertiary"], anchor="w", wraplength=510, justify="left", font=("Segoe UI", 8)).pack(fill="x", padx=25)
        app.engine_cards.append((value, card))
    def selected(*_):
        for value, card in app.engine_cards:
            if card.winfo_exists():
                card.configure(highlightbackground=colors["blue"] if app.engine_choice_var.get() == value else colors["border"])
    app.engine_choice_var.trace_add("write", selected)
    selected()
    actions = tk.Frame(engine, bg=colors["bg"])
    actions.pack(fill="x", pady=8)
    ttk.Button(actions, text="Run check", command=app.open_speed_check, style="Mac.TButton").pack(side="left")
    ttk.Button(actions, text="Manage keys", command=app.open_provider_settings, style="Mac.TButton").pack(side="right")
    factories = provider_factories()
    app.engine_provider_widgets = {}
    for kind, label in (("asr", "Recognition"), ("mt", "Translation")):
        providers = ["local"] + [f.name for f in factories if f.kind == kind or (kind == "asr" and f.kind == "live")]
        variable = app.engine_default_vars[f"default_{kind}_provider"]
        app.engine_provider_widgets[kind] = field(engine, label + " provider", variable, colors, providers)
        model = field(engine, label + " model", app.engine_default_vars[f"default_{kind}_model"], colors, [])
        def refresh(*_, v=variable, m=model, k=kind):
            if m.winfo_exists():
                factory = next((f for f in factories if f.name == v.get()), None)
                from gui import WHISPER_MODELS
                choices = (factory.models if factory else
                    (tuple(WHISPER_MODELS) if k == "asr" else ("automatic", "opus", "translategemma")) if v.get() == "local" else ())
                m.configure(values=choices)
                selected_model = app.engine_default_vars[f"default_{k}_model"]
                if choices and selected_model.get() not in choices:
                    selected_model.set(app.whisper_var.get() if not factory and k == "asr" else choices[0])
                elif not choices:
                    selected_model.set("")
        variable.trace_add("write", refresh)
        variable.trace_add("write", lambda *_: refresh_provider_choices(app))
        refresh()
    app.engine_support_var = tk.StringVar(app.root)
    tk.Label(engine, textvariable=app.engine_support_var, bg=colors["bg"], fg=colors["orange"],
             wraplength=510, justify="left", anchor="w").pack(fill="x")
    refresh_provider_choices(app)
    app.engine_budget_entry = field(engine, "Monthly budget (USD)", app.monthly_budget_var, colors)
    field(engine, "If the budget is reached", app.budget_fallback_var, colors, ("local", "stop"))
    field(engine, "Use these defaults for", app.engine_scope_var, colors, ("all", "pair"))
    heading(cost, "Cost & usage", "You pay providers for usage. Figures are estimates or conservative reservations until billing is known.", colors)
    app.cost_summary_var = tk.StringVar(value="This month $0.00 · speech sent 0 min of 0 min captured")
    tk.Label(cost, textvariable=app.cost_summary_var, bg=colors["bg"], fg=colors["text"], wraplength=560,
             justify="left", anchor="w", font=("Segoe UI Semibold", 11)).pack(fill="x", pady=(0, 16))
    app.cost_budget_entry = field(cost, "Monthly budget (USD)", app.monthly_budget_var, colors)
    field(cost, "When it is reached", app.budget_fallback_var, colors, ("local", "stop"))
    field(cost, "Warn at percent", app.budget_warning_var, colors, ("50", "75", "80", "90", "100"))
    for title, variable in (("Skip silence, music and noise", app.skip_non_speech_var), ("Skip speech outside the selected languages", app.skip_other_languages_var)):
        tk.Checkbutton(cost, text=title, variable=variable, **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=6)
    field(cost, "Close idle connections after seconds (8–10)", app.close_idle_var, colors, ("8", "9", "10"))
    app.provider_totals_var = tk.StringVar()
    tk.Label(cost, textvariable=app.provider_totals_var, bg=colors["bg"], fg=colors["secondary"], anchor="w", justify="left").pack(fill="x", pady=16)
    refresh_measurements(app)
    refresh_usage(app)


def safe_budget(value):
    try:
        return budget(value)
    except ValueError:
        return Decimal(0)


def refresh_measurements(app):
    from engines.checks import CheckStore
    descriptions = getattr(app, "engine_card_descriptions", {})
    try:
        rows = CheckStore(app.preferences.path.parent / "checks.json").results(*pair(app))
    except (ValueError, OSError, KeyError):
        rows = []
    latest = {row["engine"]: row for row in rows}
    defaults = load_engine_settings(app.preferences.path).resolve(*pair(app))
    chosen = defaults["default_asr_provider"] or "soniox"
    if hasattr(app, "empty_measurements_var"):
        recent = rows[-1] if rows else None
        app.empty_measurements_var.set((f"{recent['engine']} · measured {recent['checked_on'][:10]} · Delay "
            + (f"{recent['delay_p50_s']:.1f} s" if recent.get("delay_p50_s") is not None else "not measured"))
            if recent else "Delay and accuracy: not measured for this pair. Compare cloud and on-PC engines.")
    for kind, variable in descriptions.items():
        row = (latest.get(chosen) if kind == "cloud" else next((r for r in reversed(rows)
               if r["engine"].startswith("local:")), None) if kind == "local" else None)
        if row:
            delay = row.get("delay_p50_s")
            accuracy = row.get("words_right")
            variable.set(f"{row['engine']} · measured {row['checked_on'][:10]}\nDelay: "
                + (f"{delay:.1f} s" if delay is not None else "not measured")
                + " · Words right: " + (f"{accuracy:.1f}%" if accuracy is not None else "not measured")
                + f" · Cost: ${Decimal(row.get('cost_per_speech_hour', '0')):.3f}/speech h")
        else:
            variable.set({"cloud": "Delay and accuracy: not measured. Cost: provider list estimate; run a check.",
                "local": "Delay and accuracy: not measured on this PC. Cost: free, on this PC.",
                "free": "Delay and accuracy: not measured. Cost: free account allowances, then on this PC."}[kind])


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
