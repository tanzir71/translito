"""Inline provider connection and advanced cloud preferences."""
from ui_scale import px, scaled_geometry
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from engines.cloud_connect import CloudConnector, ConnectionError, TITLES
from engines.registry import provider_factories
from engines.settings import load_engine_settings


def provider_page(app, parent, colors):
    from engine_ui import field, heading, safe_budget
    heading(parent, "Cloud provider", "Choose a provider, connect its key and set a monthly budget.", colors)
    factories = {f.name: f for f in provider_factories()}
    primary = ("soniox", "elevenlabs", "speechmatics")
    labels = {name: f"{TITLES[name]} · " + ("recognition and translation in one stream" if name == "soniox" else
        "recognition; translation on this PC") + f" · ${factories[name].display_hourly_rate:.2f} per hour" for name in primary}
    selected = app.engine_default_vars["default_asr_provider"].get()
    provider = tk.StringVar(parent, value=labels.get(selected, labels["soniox"]))
    chooser = field(parent, "Provider", provider, colors, tuple(labels.values()))
    state = {"provider": selected if selected in primary else "soniox", "connector": None,
             "has_key": False, "busy": False}
    key = tk.StringVar(parent)
    key_row = tk.Frame(parent, bg=colors["bg"])
    key_row.pack(fill="x", pady=px((8, 0)))
    key_row.columnconfigure(0, weight=1)
    app.cloud_key_entry = ttk.Entry(key_row, textvariable=key, show="•", style="Dark.TEntry")
    app.cloud_key_entry.grid(row=1, column=0, sticky="ew")
    key_label = tk.Label(key_row, bg=colors["bg"], fg=colors["secondary"], anchor="w")
    key_label.grid(row=0, column=0, sticky="w", pady=px((0, 6)))
    actions = tk.Frame(parent, bg=colors["bg"])
    actions.pack(fill="x", pady=px((10, 0)))
    status = tk.StringVar(parent)
    app.cloud_connection_status = status
    card = tk.Frame(parent, bg=colors["surface"], padx=px(12), pady=px(10),
                    highlightbackground=colors["border"], highlightthickness=px(1))
    tk.Label(card, textvariable=status, bg=colors["surface"], fg=colors["text"],
             wraplength=px(520), justify="left", anchor="w").pack(fill="x")
    def show_status(*_):
        if status.get():
            card.pack(fill="x", after=actions, pady=px((12, 0)))
        else:
            card.pack_forget()
    status.trace_add("write", show_status)
    notice = tk.StringVar(parent)
    tk.Label(parent, textvariable=notice, bg=colors["bg"], fg=colors["tertiary"],
             wraplength=px(540), justify="left", anchor="w", font=("Segoe UI", 8)).pack(fill="x", pady=px((10, 16)))
    events = queue.Queue()
    def connector():
        if state["connector"] is None:
            from engines.secrets import CredentialStore
            credentials = getattr(app, "credential_store", None) or CredentialStore()
            state["connector"] = CloudConnector(app.preferences.path, credentials)
        return state["connector"]
    def update_actions(*_):
        busy = state["busy"]
        label = ("Connecting…" if busy else "Save new key" if state["has_key"] and key.get().strip()
                 else "Check connection" if state["has_key"] else "Connect")
        app.cloud_connect_button.configure(text=label, state="disabled" if busy else "normal")
        app.cloud_key_entry.configure(state="disabled" if busy else "normal")
        chooser.configure(state="disabled" if busy else "readonly")
        app.cloud_remove_button.configure(state="disabled" if busy else "normal")
        if state["has_key"]:
            app.cloud_remove_button.pack(side="right")
        else:
            app.cloud_remove_button.pack_forget()
    def refresh(*_):
        name = state["provider"]
        key_label.configure(text=f"{TITLES[name]} API key")
        notice.set(f"Translito checks the key with {TITLES[name]} without sending any audio, then keeps it in Windows Credential Manager." if name != "azure" else
                   "Azure has no metadata key check. Connect sends one character of public text; it may count toward your translation allowance.")
        status.set("")
        state["has_key"] = False
        if app.preview_mode:
            update_actions()
            return
        try:
            ending, checked, valid = connector().status(name)
            if ending:
                state["has_key"] = True
                checked_text = ""
                if checked:
                    local = datetime.fromisoformat(checked).astimezone()
                    checked_text = local.strftime("checked today at %H:%M") if local.date() == datetime.now().date() else local.strftime("checked %d %b at %H:%M")
                status.set(f"Connected to {TITLES[name]}\nKey ending {ending} · {checked_text}" if valid else "Saved key found · Check again")
        except Exception:
            status.set("Couldn't read the saved key. Try Connect again.")
        update_actions()
    def changed(*_):
        state["provider"] = next((name for name, label in labels.items() if label == provider.get()), state["provider"])
        app.engine_default_vars["default_asr_provider"].set(state["provider"])
        models = factories[state["provider"]].models
        if models and app.engine_default_vars["default_asr_model"].get() not in models:
            app.engine_default_vars["default_asr_model"].set(models[0])
        key.set("")
        refresh()
    chooser.bind("<<ComboboxSelected>>", changed)
    def connect():
        if app.preview_mode:
            status.set("Preview only: no key check or credential write.")
            return
        if state["busy"]:
            return
        name, pasted = state["provider"], key.get()
        account_kind = "paid" if app.engine_choice_var.get() == "cloud" else "free"
        state["busy"] = True
        update_actions()
        status.set(f"Connecting to {TITLES[name]}…")
        controller = connector()
        def work():
            try:
                controller.connect(name, pasted, account_kind=account_kind)
                events.put((name, ""))
            except ConnectionError as error:
                events.put((name, str(error)))
            except Exception:
                events.put((name, "Couldn't save the key. Check Windows Credential Manager and try again."))
        threading.Thread(target=work, daemon=True, name="Connect provider").start()
    app.cloud_connect_button = ttk.Button(actions, text="Connect", width=px(16, chars=True), command=connect, style="Primary.TButton")
    app.cloud_connect_button.pack(side="left", padx=px((0, 8)))
    app.cloud_connect = connect
    ttk.Button(actions, text="Get a key ↗", width=px(14, chars=True), style="Mac.TButton",
               command=lambda: webbrowser.open(factories[state["provider"]].setup_url)).pack(side="left")
    def remove():
        if app.preview_mode:
            return
        connector().remove(state["provider"])
        state["has_key"] = False
        key.set("")
        status.set("Key removed")
        update_actions()
        from engine_ui import refresh_engine_status
        refresh_engine_status(app)
    app.cloud_remove_button = ttk.Button(actions, text="Remove key", width=px(14, chars=True), style="Mac.TButton", command=remove)
    key.trace_add("write", update_actions)
    update_actions()
    app.cloud_remove = remove
    app.cloud_key_var = key
    app.cloud_provider_var = provider
    app.engine_budget_entry = field(parent, "Monthly budget (USD)", app.monthly_budget_var, colors)
    field(parent, "When the budget is used up", app.budget_fallback_var, colors,
          ("Continue on this PC", "Stop the session"))
    budget_text = tk.StringVar(parent)
    budget_label = tk.Label(parent, textvariable=budget_text, bg=colors["bg"], fg=colors["orange"],
                            wraplength=px(540), justify="left", anchor="w", font=("Segoe UI", 8))
    budget_label.pack(fill="x", pady=px(8))
    def budget_changed(*_):
        amount = safe_budget(app.monthly_budget_var.get())
        rate = factories[state["provider"]].display_hourly_rate
        budget_text.set("Paid use starts once the monthly budget is above $0. Until then sessions run on this PC." if not amount else
            f"About {int(amount/rate)} hours of speech a month at ${rate:.2f} per hour. You get a warning at 80%.")
        budget_label.configure(fg=colors["orange"] if not amount else colors["secondary"])
        from engine_ui import refresh_engine_status
        refresh_engine_status(app)
    app.monthly_budget_var.trace_add("write", budget_changed)
    budget_changed()
    def poll():
        if not parent.winfo_exists():
            return
        while True:
            try:
                name, error = events.get_nowait()
            except queue.Empty:
                break
            state["busy"] = False
            update_actions()
            if name != state["provider"]:
                continue
            if error:
                status.set(error)
            else:
                key.set("")
                app.engine_default_vars["default_asr_provider"].set(name)
                if factories[name].models and app.engine_default_vars["default_asr_model"].get() not in factories[name].models:
                    app.engine_default_vars["default_asr_model"].set(factories[name].models[0])
                refresh()
            from engine_ui import refresh_engine_status
            refresh_engine_status(app)
        parent.after(100, poll)
    app.refresh_cloud_connection = refresh
    # Reading a key is deferred until the owner opens Engine, never at startup.
    on_page = app.settings_shell.on_page
    def page_opened(name):
        on_page(name)
        if name == "Engine":
            refresh()
    app.settings_shell.on_page = page_opened
    if app.settings_shell.current == "Engine":
        refresh()
    poll()
