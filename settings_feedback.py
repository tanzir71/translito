"""Save status is delivered from the writer to Tk by a main-thread poll."""
import queue
import time
import tkinter as tk
from tkinter import ttk


def add_footer(app, window, colors):
    footer = tk.Frame(window, bg=colors["bg"], padx=24, pady=12)
    footer.pack(side="bottom", fill="x")
    tk.Label(footer, text="Changes save automatically", bg=colors["bg"], fg=colors["tertiary"],
             font=("Segoe UI", 8)).pack(side="left")
    app.save_status_var = tk.StringVar(window)
    retry = ttk.Button(footer, text="Retry", style="Mac.TButton", command=app.preferences.store.retry)
    status = tk.Label(footer, textvariable=app.save_status_var, bg=colors["bg"], fg=colors["green"],
                      font=("Segoe UI", 8), wraplength=380, justify="right")
    status.pack(side="right")
    until = [0]
    def poll():
        if not window.winfo_exists():
            return
        store = app.preferences.store
        while True:
            try:
                kind, value = store.events.get_nowait()
            except queue.Empty:
                break
            if kind == "saved":
                app.save_status_var.set("✓ Saved")
                status.configure(fg=colors["green"])
                until[0] = time.monotonic() + 2
                retry.pack_forget()
            else:
                app.save_status_var.set(f"Couldn't save: {value}" + (". Retrying…" if kind == "retrying" else ""))
                status.configure(fg=colors["red"])
                until[0] = 0
                if kind == "error":
                    retry.pack(side="right", padx=8)
        if until[0] and time.monotonic() >= until[0]:
            app.save_status_var.set("")
            until[0] = 0
        window.after(100, poll)
    poll()
