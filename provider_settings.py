"""Provider cards using the existing Windows Tk styles."""
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from app_config import CONFIG_FILE
from engines.display import display_text
from engines.registry import provider_factories
from engines.settings import ProviderSettings, load_engine_settings
from engines.setup import ProviderSetup
from engines.usage import UsageLedger
from quality_settings import _entry, _window


def open_provider_settings(app, colors, center):
    window = _window(app, "Cloud providers and usage", colors, center, 660, 610)
    app.style.configure("Provider.TNotebook", background=colors["bg"], borderwidth=0)
    app.style.configure("Provider.TNotebook.Tab", padding=(10, 7))
    notebook = ttk.Notebook(window, style="Provider.TNotebook")
    notebook.pack(fill="both", expand=True, padx=12, pady=12)
    settings = load_engine_settings(CONFIG_FILE)
    controller = ProviderSetup(path=CONFIG_FILE, on_event=app.on_event)
    short_names = {"cohere-api": "Cohere", "groq": "Groq", "azure": "Azure", "deepl": "DeepL", "google": "Google", "gemini": "Gemini"}

    def card(factory):
        preference = settings.provider(factory.name)
        body = tk.Frame(notebook, bg=colors["bg"], padx=16, pady=12)
        notebook.add(body, text=short_names[factory.name])
        tk.Label(body, text=factory.title, bg=colors["bg"], fg=colors["text"],
                 font=("Segoe UI Semibold", 12), anchor="w").pack(fill="x")
        tk.Label(body, text=factory.quota_label, bg=colors["bg"], fg=colors["secondary"], anchor="w").pack(fill="x", pady=(2, 6))
        tk.Label(body, text=factory.privacy_note, bg=colors["bg"], fg=colors["secondary"],
                 wraplength=590, justify="left", anchor="w").pack(fill="x", pady=4)
        ttk.Button(body, text="How to get a free key / review terms", style="Mac.TButton",
                   command=lambda: webbrowser.open(factory.setup_url)).pack(anchor="w", pady=4)
        confirmed = tk.BooleanVar(value=preference.account_kind == factory.account_kind)
        training = tk.BooleanVar(value=preference.training_consent)
        enabled = tk.BooleanVar(value=preference.enabled)
        key = tk.StringVar()
        region = tk.StringVar(value=preference.region)
        account_text = {"azure": "This is an Azure Translator F0 key", "deepl": "This is a DeepL API Free key (ends in :fx)",
                        "google": "This project has unused monthly Translation credit and is dedicated to Translito",
                        "cohere-api": "This is a Cohere free trial key (no payment method)",
                        "gemini": "This is a Gemini free-tier project key", "groq": "This is a Groq Free account key"}[factory.name]
        tk.Checkbutton(body, text=account_text, variable=confirmed,
                       **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=3)
        if factory.training_required:
            tk.Checkbutton(body, text="I understand and accept the provider's input/output reuse terms", variable=training,
                           **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=3)
        _entry(body, "API key", key, colors, secret=True)
        if factory.name == "azure":
            _entry(body, "Azure region", region, colors)
        tk.Checkbutton(body, text="Enable after a successful Test", variable=enabled,
                       **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=4)
        tk.Label(body, text="Paid cap: $0 — this card uses only free allowances. Leave the key blank to use its saved copy.",
                 bg=colors["bg"], fg=colors["secondary"], wraplength=590, justify="left").pack(fill="x", pady=4)
        usage = tk.StringVar()
        bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        bar.pack(fill="x", pady=(5, 2))
        tk.Label(body, textvariable=usage, bg=colors["bg"], fg=colors["secondary"], anchor="w").pack(fill="x")
        status = tk.StringVar(value="Tested key saved" if preference.tested_signature else "No tested key. Keys are saved only in Windows Credential Manager.")

        def refresh_usage():
            try:
                ledger = UsageLedger()
                data = ledger.snapshot()["providers"].get(factory.name, {}) if not app.preview_mode and ledger.path.exists() else {}
                used = data.get(factory.monthly_unit, 0)
                if factory.monthly_limit:
                    usage.set(f"Free this month: {used:,.0f} of {factory.monthly_limit:,} {factory.monthly_unit.replace('_', ' ')} used")
                    bar["value"] = min(100, 100 * used / factory.monthly_limit)
                else:
                    label = f"{used / 3600:.2f} audio hours" if factory.monthly_unit == "audio_seconds" else f"{used:,.0f} characters"
                    usage.set("This month: " + label + "; account limits apply")
                    bar["value"] = 0
            except Exception:
                usage.set("Usage history could not be read; it was preserved.")
        refresh_usage()

        def values():
            return ProviderSettings(enabled=enabled.get(), region=region.get().strip() if factory.name == "azure" else "",
                account_kind=factory.account_kind if confirmed.get() else "unconfirmed", training_consent=training.get())

        def run(test):
            if app.preview_mode:
                status.set("Preview only: no keys are read/saved and no requests or settings writes occur.")
                return
            if app.transcriber is not None or app.model_setup_busy:
                status.set("Finish the current session or setup first.")
                return
            selected, entered_key = values(), key.get()
            key.set("")
            app.configure_offline_env()
            app.model_setup_busy = True
            app.update_action_button(running=False, loading=True)
            for button in buttons:
                button.configure(state="disabled")
            status.set("Testing public sample…" if test else "Saving preferences…")
            def work():
                try:
                    if test:
                        result = controller.test(factory.name, selected, key=entered_key)
                        message = f"Passed in {result.latency_s:.2f}s. " + ("Enabled. " if result.enabled else "Check Enable and Save to use it. ") + display_text(result.text[:100])
                    else:
                        controller.save_preference(factory.name, selected, key=entered_key)
                        message = "Preferences saved."
                except Exception as exc:
                    # Setup errors are static; never display an unexpected SDK traceback.
                    from engines.setup import SetupError
                    message = str(exc) if isinstance(exc, SetupError) else "Setup failed. Check the key, account and connection."
                def finish():
                    app.model_setup_busy = False
                    app.finish_model_progress()
                    app.set_status("Ready")
                    app.update_action_button(running=False)
                    app.on_event("engine", {"asr": "Local", "mt": "Local", "fallback": False})
                    if window.winfo_exists():
                        for button in buttons:
                            button.configure(state="normal")
                        status.set(message)
                        refresh_usage()
                try:
                    app.root.after(0, finish)
                except (RuntimeError, tk.TclError):
                    pass
            threading.Thread(target=work, daemon=True).start()
        row = tk.Frame(body, bg=colors["bg"])
        row.pack(fill="x", pady=8)
        buttons = [ttk.Button(row, text="Save key and Test", style="Primary.TButton", command=lambda: run(True)),
                   ttk.Button(row, text="Save preference", style="Mac.TButton", command=lambda: run(False))]
        for button in buttons:
            button.pack(side="left", padx=(0, 8))
        tk.Label(body, textvariable=status, bg=colors["bg"], fg=colors["secondary"], wraplength=590,
                 justify="left", anchor="w").pack(fill="x", pady=4)
        sample = "Test translates ‘Good morning’." if factory.kind == "mt" else "Test uploads the bundled public Arabic clip; no microphone is used."
        tk.Label(body, text=sample + " Usage covers Translito only.", bg=colors["bg"], fg=colors["secondary"],
                 wraplength=590, justify="left", anchor="w").pack(fill="x", pady=4)

    for factory in provider_factories():
        card(factory)
    return window
