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
        app.offline_only_var.set(choice == "local")
        app.engine_profile_var.set({"cloud": "Custom", "local": "Offline (private)", "free": "Free (recommended)"}[choice])
        app.change_engine_profile()
    app.engine_choice_var.trace_add("write", choice_changed)
    app.engine_scope_var.trace_add("write", lambda *_: restore_scope(app))


def pair(app):
    return tuple(app.language_entry_by_name(v.get())[2] for v in (app.listen_source_var, app.listen_target_var))


def save_default(app, key, value):
    if getattr(app, "_loading_engine_scope", False):
        return
    source, target = pair(app)
    key = key if app.engine_scope_var.get() == "all" else f"pair_{source}_{target}_{key.removeprefix('default_')}"
    app.preferences.set("ENGINES", key, value)


def restore_scope(app):
    app._loading_engine_scope = True
    settings = load_engine_settings(app.preferences.path)
    for key, variable in app.engine_default_vars.items():
        variable.set(getattr(settings, key) if app.engine_scope_var.get() == "all" else settings.resolve(*pair(app))[key])
    app._loading_engine_scope = False


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
    for value, title, description in (
        ("cloud", "Cloud, pay as you go", "Sends gated speech. Delay and accuracy: not measured. Cost: list estimate; see provider."),
        ("local", "On this PC", "Free and private. Delay and accuracy: run a check on this PC."),
        ("free", "Free cloud allowances", "Tested free accounts, then local fallback. Delay and accuracy: not measured.")):
        card = tk.Frame(engine, bg=colors["bg"], highlightthickness=1, highlightbackground=colors["border"], padx=12, pady=10, takefocus=True)
        card.pack(fill="x", pady=(0, 8))
        radio = tk.Radiobutton(card, text=title, variable=app.engine_choice_var, value=value, bg=colors["bg"], fg=colors["text"],
            selectcolor=colors["field"], activebackground=colors["bg"], activeforeground=colors["text"], font=("Segoe UI", 10), anchor="w")
        radio.pack(fill="x")
        tk.Label(card, text=description, bg=colors["bg"], fg=colors["tertiary"], anchor="w", wraplength=510, justify="left", font=("Segoe UI", 8)).pack(fill="x", padx=25)
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
    for kind, label in (("asr", "Recognition"), ("mt", "Translation")):
        providers = ["local"] + [f.name for f in factories if f.kind == kind or (kind == "asr" and f.kind == "live")]
        variable = app.engine_default_vars[f"default_{kind}_provider"]
        field(engine, label + " provider", variable, colors, providers)
        model = field(engine, label + " model", app.engine_default_vars[f"default_{kind}_model"], colors, [])
        def refresh(*_, v=variable, m=model):
            if m.winfo_exists():
                factory = next((f for f in factories if f.name == v.get()), None)
                m.configure(values=factory.models if factory else ("Use selected local model",))
        variable.trace_add("write", refresh)
        refresh()
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
    refresh_usage(app)


def refresh_usage(app):
    if app.preview_mode:
        return
    try:
        snapshot = UsageLedger().snapshot()
        providers = snapshot["providers"]
        spent = sum((Decimal(p["estimated_usd"]) for p in providers.values()), Decimal(0))
        sessions = snapshot.get("sessions", {}).values()
        captured = sum(s.get("captured_seconds", 0) for s in sessions)
        sent = sum(s.get("sent_seconds", 0) for s in sessions)
        if hasattr(app, "cost_summary_var"):
            app.cost_summary_var.set(f"This month ${spent:.2f} of ${budget(app.monthly_budget_var.get()):.2f} · {sent/60:.1f} of {captured/60:.1f} min sent")
            app.provider_totals_var.set("\n".join(f"{name}   ${Decimal(p['estimated_usd']):.4f} estimated" for name, p in providers.items()) or "No cloud usage recorded.")
        app.month_cost_var.set(f"This month ${spent:.2f} / ${budget(app.monthly_budget_var.get()):.2f}")
        interpreter = getattr(getattr(app.transcriber, "conversation_pipeline", None), "interpreter", None)
        guard = getattr(interpreter, "guard", None)
        if guard:
            app.session_cost_var.set(f"Session · {guard.sent_seconds/60:.1f} / {guard.captured_seconds/60:.1f} min sent")
    except (ValueError, OSError, RuntimeError):
        app.month_cost_var.set("This month unavailable")
