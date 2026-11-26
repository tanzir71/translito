"""Advanced provider connections; checks metadata instead of running a sample."""
from ui_scale import px, scaled_geometry
import queue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from engines.cloud_connect import CloudConnector, ConnectionError, TITLES
from engines.registry import provider_factories
from engines.settings import load_engine_settings
from engine_ui import field, heading
from quality_settings import _window


def open_provider_settings(app, colors, center):
    window = _window(app, "Advanced cloud providers", colors, center, 560, 524)
    body = tk.Frame(window, bg=colors["bg"], padx=px(24), pady=px(22))
    body.pack(fill="both", expand=True)
    heading(body, "Advanced cloud providers", "Connect a saved key or replace it. No audio is sent by Connect.", colors)
    factories = {f.name: f for f in provider_factories()}
    provider = tk.StringVar(window, value=app.engine_default_vars["default_asr_provider"].get() or "soniox")
    if provider.get() not in factories:
        provider.set("soniox")
    field(body, "Cloud provider", provider, colors, tuple(factories))
    key, limit, region = tk.StringVar(window), tk.StringVar(window), tk.StringVar(window)
    field(body, "API key (blank uses its saved copy)", key, colors).configure(show="•")
    field(body, "Provider limit (blank: Use the monthly budget)", limit, colors)
    field(body, "Azure region", region, colors)
    consent = tk.BooleanVar(window)
    tk.Checkbutton(body, text="I accept the provider's free-tier data-use terms", variable=consent,
        **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=px(8))
    details, status = tk.StringVar(window), tk.StringVar(window)
    tk.Label(body, textvariable=details, bg=colors["bg"], fg=colors["secondary"], wraplength=px(500), justify="left").pack(fill="x", pady=px(8))
    tk.Label(body, textvariable=status, bg=colors["bg"], fg=colors["text"], wraplength=px(500), justify="left").pack(fill="x", pady=px(8))
    loading, events = [False], queue.Queue()
    def controller():
        from engines.secrets import CredentialStore
        return CloudConnector(app.preferences.path, getattr(app, "credential_store", None) or CredentialStore())
    def restore(*_):
        loading[0] = True
        name = provider.get()
        saved = load_engine_settings(app.preferences.path).provider(name)
        limit.set("" if saved.inherit_monthly_cap else str(saved.monthly_cap))
        region.set(saved.region)
        consent.set(saved.training_consent)
        details.set(factories[name].privacy_note + (" Connect sends one character of public text to Azure." if name == "azure" else " Connect checks authenticated metadata without sending audio."))
        if not app.preview_mode:
            try:
                ending, checked, valid = controller().status(name)
                status.set((f"Connected to {TITLES[name]} · key ending {ending}" if valid else "Saved key found · Check again") if ending else "Paste a key to connect.")
            except Exception:
                status.set("Could not read the saved key. Try Connect.")
        loading[0] = False
    provider.trace_add("write", restore)
    def save(*_):
        if loading[0]:
            return
        prefix = provider.get().replace("-", "_") + "_"
        good = app.preferences.set("ENGINES", prefix + "monthly_cap_usd", limit.get(), delay=.4)
        app.preferences.set("ENGINES", prefix + "region", region.get(), delay=.4)
        app.preferences.set("ENGINES", prefix + "training_consent", consent.get())
        status.set("" if good else "Enter an amount like 5 or 12.50")
    for variable in (limit, region, consent):
        variable.trace_add("write", save)
    def connect():
        if app.preview_mode:
            status.set("Preview only: no keys, network requests or writes.")
            return
        name, entered = provider.get(), key.get()
        factory = factories[name]
        kind = "paid" if name in {"soniox", "elevenlabs", "speechmatics"} or (name == "gemini" and app.engine_choice_var.get() == "cloud") else factory.account_kind
        action.configure(state="disabled")
        connection = controller()
        def work():
            try:
                connection.connect(name, entered, account_kind=kind)
                events.put((name, ""))
            except ConnectionError as error:
                events.put((name, str(error)))
            except Exception:
                events.put((name, "Couldn't save the key. Check Credential Manager and retry."))
        threading.Thread(target=work, daemon=True).start()
    action = ttk.Button(body, text="Connect", style="Primary.TButton", command=connect)
    action.pack(anchor="e", pady=px(10))
    ttk.Button(body, text="Get a key ↗", style="Mac.TButton", command=lambda: webbrowser.open(factories[provider.get()].setup_url)).pack(anchor="w")
    def poll():
        if not window.winfo_exists():
            return
        while True:
            try:
                name, error = events.get_nowait()
            except queue.Empty:
                break
            action.configure(state="normal")
            if error:
                status.set(error)
            else:
                key.set("")
                kind = "mt" if factories[name].kind == "mt" else "asr"
                app.engine_default_vars[f"default_{kind}_provider"].set(name)
                if factories[name].models and app.engine_default_vars[f"default_{kind}_model"].get() not in factories[name].models:
                    app.engine_default_vars[f"default_{kind}_model"].set(factories[name].models[0])
                restore()
        window.after(100, poll)
    restore()
    poll()
    window.provider_var, window.key_var = provider, key
    return window
