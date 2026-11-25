"""One cloud connection dialog; secrets are saved only by the explicit Test action."""
from dataclasses import replace
from decimal import Decimal
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from app_config import CONFIG_FILE
from engines.registry import provider_factories
from engines.settings import ProviderSettings, budget, load_engine_settings
from engines.setup import ProviderSetup, SetupError
from engine_ui import field, heading, pair
from quality_settings import _window


def open_provider_settings(app, colors, center):
    window = _window(app, "Connect a cloud provider", colors, center, 560, 524)
    from gui import ScrollableFrame
    from ui_theme import dark_titlebar
    window.after_idle(lambda: dark_titlebar(window))
    scroll = ScrollableFrame(window, background=colors["bg"])
    scroll.pack(fill="both", expand=True)
    body = scroll.content
    body.configure(padx=24, pady=22)
    heading(body, "Connect a cloud provider", "Paste a key, test it on a public sample, and set a monthly limit.", colors)
    factories = {factory.name: factory for factory in provider_factories()}
    provider = tk.StringVar(value=app.engine_default_vars["default_asr_provider"].get())
    if provider.get() not in factories:
        provider.set(next(iter(factories)))
    field(body, "Provider", provider, colors, list(factories))
    details = tk.StringVar()
    tk.Label(body, textvariable=details, bg=colors["bg"], fg=colors["tertiary"], wraplength=500, justify="left", anchor="w").pack(fill="x", pady=8)
    key, limit, account = tk.StringVar(), tk.StringVar(), tk.StringVar()
    field(body, "API key (leave blank to use its saved copy)", key, colors).configure(show="•")
    ttk.Button(body, text="Get a key", style="Mac.TButton", command=lambda: webbrowser.open(factories[provider.get()].setup_url)).pack(anchor="e")
    field(body, "Account tier", account, colors, ("unconfirmed", "free", "trial", "paid"))
    field(body, "Monthly limit for this provider (USD)", limit, colors)
    consent, enabled = tk.BooleanVar(), tk.BooleanVar()
    tk.Checkbutton(body, text="I accept the provider's data-use terms for free/trial use", variable=consent,
        **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=6)
    tk.Checkbutton(body, text="Use this tested provider", variable=enabled,
        **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=6)
    make_default = tk.BooleanVar(value=True)
    tk.Checkbutton(body, text="Make this my default provider", variable=make_default,
        **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=6)
    region = tk.StringVar()
    region_entry = field(body, "Region (Azure only)", region, colors)
    status = tk.StringVar()
    tk.Label(body, textvariable=status, bg=colors["green_bg"], fg=colors["text"], wraplength=480, justify="left", anchor="w", padx=12, pady=10).pack(fill="x", pady=8)
    controller = ProviderSetup(path=CONFIG_FILE, on_event=app.on_event)
    loading = [False]
    def restore(*_):
        loading[0] = True
        factory = factories[provider.get()]
        saved = load_engine_settings(CONFIG_FILE).provider(factory.name)
        key.set("")
        limit.set(str(saved.monthly_cap))
        account.set(saved.account_kind)
        consent.set(saved.training_consent)
        enabled.set(saved.enabled)
        region.set(saved.region)
        unavailable = factory.unavailable_reason(*pair(app))
        details.set(factory.privacy_note + (" Rate checked " + factory.rate_checked_on + "; list estimate." if factory.rate_checked_on else " Free allowance/account limits apply.") + (" " + unavailable if unavailable else ""))
        region_entry.configure(state="normal" if factory.name == "azure" else "disabled")
        button.configure(state="disabled" if unavailable else "normal")
        status.set("Tested key saved" if saved.tested_signature else "Connect starts disabled. Test is required before use.")
        loading[0] = False
    provider.trace_add("write", restore)
    def preference():
        return ProviderSettings(enabled=enabled.get(), monthly_cap=budget(limit.get()), region=region.get().strip(),
            account_kind=account.get(), training_consent=consent.get())
    def save_changed(*_):
        if loading[0] or app.preview_mode:
            return
        try:
            controller.save_preference(provider.get(), preference())
        except (ValueError, SetupError) as error:
            status.set(str(error))
    for variable in (limit, account, consent, enabled, region):
        variable.trace_add("write", save_changed)
    def test():
        if app.preview_mode:
            status.set("Preview: no keys, network requests or settings writes.")
            return
        if app.transcriber is not None or app.model_setup_busy:
            status.set("Finish the current session first.")
            return
        try:
            chosen, selected = provider.get(), replace(preference(), enabled=True)
        except ValueError as error:
            status.set(str(error))
            return
        entered = key.get()
        key.set("")
        app.configure_offline_env()
        button.configure(state="disabled")
        app.model_setup_busy = True
        status.set("Testing the bundled public sample…")
        def work():
            try:
                result = controller.test(chosen, selected, key=entered)
                message = f"Test passed in {result.latency_s:.2f} s. Provider connected."
                success = True
            except Exception as error:
                message = str(error) if isinstance(error, SetupError) else "Provider test failed. Check the key and account."
                success = False
            def finish():
                app.model_setup_busy = False
                if window.winfo_exists():
                    button.configure(state="normal")
                    loading[0] = True
                    enabled.set(success)
                    loading[0] = False
                    status.set(message)
                if success and make_default.get():
                    kind = "mt" if factories[chosen].kind == "mt" else "asr"
                    app.engine_default_vars[f"default_{kind}_provider"].set(chosen)
                    if factories[chosen].models:
                        app.engine_default_vars[f"default_{kind}_model"].set(factories[chosen].models[0])
            app.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()
    button = ttk.Button(body, text="Test and connect", style="Primary.TButton", command=test)
    button.pack(anchor="e", pady=10)
    restore()
    window.provider_var, window.key_var = provider, key
    return window
