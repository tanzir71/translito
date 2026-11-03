"""Model inventory, explicit downloads and confirmed cache deletion."""
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from engines.model_library import ModelLibrary, format_size


class ModelManagerWindow:
    def __init__(self, app, colors, center, *, library=None, auto_refresh=True):
        self.app, self.colors = app, colors
        self.library = library or ModelLibrary(session_active=lambda: app.transcriber is not None,
                                               offline=lambda: app.offline_only_var.get())
        self.rows, self.busy, self.scanning = {}, False, False
        self.window = tk.Toplevel(app.root)
        self.window.title("Manage models")
        self.window.configure(bg=colors["bg"])
        self.window.minsize(780, 480)
        self.window.transient(app.root)
        body = tk.Frame(self.window, bg=colors["bg"], padx=18, pady=16)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Models on this PC", bg=colors["bg"], fg=colors["text"],
                 font=("Segoe UI Semibold", 14)).pack(anchor="w")
        tk.Label(body, text="Download a model once, or delete a cached copy to recover disk space.",
                 bg=colors["bg"], fg=colors["secondary"]).pack(anchor="w", pady=(4, 12))
        toolbar = tk.Frame(body, bg=colors["bg"])
        toolbar.pack(fill="x", pady=(0, 10))
        self.filter = tk.StringVar(value="All models")
        combo = ttk.Combobox(toolbar, state="readonly", textvariable=self.filter,
                             values=("All models", "Downloaded", "Available / partial"), width=24)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _event: self.render())
        self.refresh_button = ttk.Button(toolbar, text="Refresh", command=self.refresh)
        self.refresh_button.pack(side="right")
        table = tk.Frame(body, bg=colors["bg"])
        table.pack(fill="both", expand=True)
        columns = ("model", "kind", "status", "size", "storage")
        style = ttk.Style(self.window)
        style.configure("Models.Treeview", background=colors["surface"], fieldbackground=colors["surface"],
                        foreground=colors["text"], rowheight=28)
        style.configure("Models.Treeview.Heading", background=colors["surface_2"], foreground=colors["text"])
        style.map("Models.Treeview", background=[("selected", colors["blue"])], foreground=[("selected", "white")])
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse", height=12,
                                 style="Models.Treeview")
        for key, title, width in (("model", "Model", 290), ("kind", "Use", 85), ("status", "Status", 100),
                                  ("size", "Disk use", 90), ("storage", "Location", 175)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=65, stretch=key in {"model", "storage"})
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.selection_changed())
        self.detail = tk.StringVar(value="Reading local model caches…")
        tk.Label(body, textvariable=self.detail, bg=colors["bg"], fg=colors["secondary"],
                 anchor="w", justify="left", wraplength=820, height=3).pack(fill="x", pady=8)
        buttons = tk.Frame(body, bg=colors["bg"])
        buttons.pack(fill="x")
        self.download_button = ttk.Button(buttons, text="Download", command=self.download)
        self.download_button.pack(side="left", padx=(0, 8))
        self.delete_button = ttk.Button(buttons, text="Delete cached files…", command=self.delete)
        self.delete_button.pack(side="left", padx=(0, 8))
        self.folder_button = ttk.Button(buttons, text="Open folder", command=self.open_folder)
        self.folder_button.pack(side="left")
        self.status = tk.StringVar(value="Listing models uses no network.")
        tk.Label(body, textvariable=self.status, bg=colors["bg"], fg=colors["secondary"],
                 wraplength=820, anchor="w", justify="left").pack(fill="x", pady=(10, 0))
        center(self.window, app.root, width=900, height=580)
        if auto_refresh:
            self.refresh()

    def dispatch(self, callback):
        try:
            if not self.app.is_quitting:
                self.app.root.after(0, lambda: callback() if self.window.winfo_exists() else None)
        except (RuntimeError, tk.TclError):
            pass

    def refresh(self):
        if self.busy or self.scanning:
            return
        self.scanning = True
        self.refresh_button.configure(state="disabled")
        self.selection_changed()
        def work():
            try:
                rows, error = self.library.inventory(), None
            except Exception:
                rows, error = [], "Could not read a model cache. Check that its drive is connected, then refresh."
            def done():
                self.scanning = False
                self.rows = {row.key: row for row in rows}
                self.refresh_button.configure(state="normal")
                self.render()
                self.status.set(error or "Select a model to download, view its folder, or remove its cached copy.")
            self.dispatch(done)
        threading.Thread(target=work, daemon=True, name="Translito model inventory").start()

    def render(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self.rows.values():
            if self.filter.get() == "Downloaded" and row.status != "Downloaded":
                continue
            if self.filter.get() == "Available / partial" and row.status == "Downloaded":
                continue
            self.tree.insert("", "end", iid=row.key, values=(row.spec.title, row.spec.kind, row.status,
                              format_size(row.size) if row.size else "—", row.storage))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        self.selection_changed()

    def selected(self):
        selection = self.tree.selection()
        return self.rows.get(selection[0]) if selection else None

    def selection_changed(self):
        row = self.selected()
        available = not self.busy and not self.scanning and not self.app.model_setup_busy and self.app.transcriber is None
        self.download_button.configure(text="Set up / download…" if row and row.spec.setup else "Download",
                                       state="normal" if row and available and (row.spec.setup or row.status != "Downloaded") and row.spec.repo else "disabled")
        self.delete_button.configure(state="normal" if row and available and row.deletable and row.status != "Available" else "disabled")
        self.folder_button.configure(state="normal" if row and not self.busy and row.path.exists() else "disabled")
        self.detail.set(f"{row.spec.repo or row.spec.title}\n{row.path}" +
                        ("\nExternal folder: view here; manage its files outside Translito." if not row.deletable and row.status != "Available" else "")
                        if row else "Select a model. Shared-cache sizes may include files used by other applications.")

    def can_modify(self):
        if self.app.preview_mode:
            self.status.set("Preview only: no files are downloaded or deleted.")
            return False
        if self.busy or self.scanning or self.app.model_setup_busy or self.app.transcriber is not None:
            self.status.set("Finish the current session or model operation first.")
            return False
        return True

    def run(self, action, success):
        self.busy = self.app.model_setup_busy = True
        self.app.lock_controls(True)
        self.app.update_action_button(loading=True)
        self.refresh_button.configure(state="disabled")
        self.selection_changed()
        def work():
            try:
                action()
                error = None
            except Exception as exc:
                from engines.model_library import ModelLibraryError
                error = str(exc) if isinstance(exc, (ModelLibraryError, RuntimeError)) else "Model files could not be changed. Check free space, permissions and other apps using this model."
            def done():
                self.busy = self.app.model_setup_busy = False
                self.app.lock_controls(False)
                self.app.update_action_button()
                self.app.set_status("Ready")
                self.app.finish_model_progress()
                self.app.show_hint(error or success)
                self.refresh_button.configure(state="normal")
                self.status.set(error or success)
                self.refresh()
            # Restore the host even if the manager was closed mid-download.
            try:
                self.app.root.after(0, lambda: done() if self.window.winfo_exists() else self.finish_closed())
            except (RuntimeError, tk.TclError):
                pass
        threading.Thread(target=work, daemon=True, name="Translito model operation").start()

    def finish_closed(self):
        self.busy = self.app.model_setup_busy = False
        self.app.lock_controls(False)
        self.app.update_action_button()
        self.app.finish_model_progress()
        self.app.set_status("Ready")

    def download(self):
        row = self.selected()
        if row is None or not self.can_modify():
            return
        if self.app.offline_only_var.get():
            self.status.set("Offline mode is on. Turn it off before downloading models.")
            return
        if row.spec.setup:
            if row.spec.setup == "cohere":
                self.app.open_arabic_model_setup()
            else:
                self.app.open_translation_model_setup()
            return
        self.status.set(f"Downloading {row.spec.title}…")
        def progress(kind, payload):
            if kind == "model_progress":
                self.dispatch(lambda: self.status.set(payload.get("phase", "Downloading…")))
        self.run(lambda: self.library.download(row, on_event=progress), "Model downloaded. It is available for the next session.")

    def delete(self):
        row = self.selected()
        if row is None or not self.can_modify() or not row.deletable:
            return
        shared = "\nThis cache may also be used by other applications." if row.storage == "Shared Hugging Face cache" else ""
        if not messagebox.askyesno("Delete model files?", f"Delete {row.spec.title}'s cached copy ({format_size(row.size)})?\n\n"
                                  f"{row.path}\n\nYou will need to download it again to use it.{shared}", parent=self.window, default="no"):
            return
        if not self.can_modify():
            return
        self.status.set(f"Removing {row.spec.title}…")
        self.run(lambda: self.library.delete(row, confirmed=True), "Cached model removed. Refresh shows the remaining copies.")

    def open_folder(self):
        row = self.selected()
        if row is None:
            return
        path = row.path if row.path.is_dir() else row.path.parent
        if path.is_dir():
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
