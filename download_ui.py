"""Tk views of the process download queue. All callbacks run on the Tk thread."""
from ui_scale import px, scaled_geometry
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


def initialize(app, colors):
    from engines.downloads import DownloadManager
    app.download_text = tk.StringVar(app.root)
    app.download_chip = ttk.Button(app.status_bar, textvariable=app.download_text, style="Mac.TButton",
                                  command=lambda: show_models(app))
    def changed(job):
        if job.state == "Ready":
            message = f"{job.title} is ready. It will be used from your next session."
            app.show_hint(message)
            from types import SimpleNamespace
            app.schedule_controller.toast(SimpleNamespace(title=message, download=True))
            if job.gemma:
                from engines.mt_translategemma import MANIFEST
                app.preferences.set("ENGINES", "translategemma_path", str(Path(job.ready_path) / MANIFEST["filename"]))
        active = next((j for j in app.download_manager.jobs if j.state in {"Downloading", "Verifying", "Stalled · retrying"}), None)
        app.download_status_text = f"↓ {active.title} {active.fraction:.0%}" if active else ""
        app.download_text.set(app.download_status_text)
        if active:
            app.download_chip.grid(row=1, column=0, columnspan=4, sticky="w")
        else:
            app.download_chip.grid_remove()
        app.update_action_button(running=app.transcriber is not None)
        app.refresh_tray_menu()
        for callback in list(getattr(app, "download_views", [])):
            callback(job)
    app.download_views = []
    app.download_manager = DownloadManager(app.root, directory=app.preferences.path.parent / "downloads",
        on_change=changed, blocked=lambda: app.offline_only_var.get())


def show_models(app):
    app.open_settings()
    app.settings_shell.show("Models")


def gemma_dialog(app, colors, center):
    from engines.mt_translategemma import MANIFEST, GEMMA_TERMS_URL, configured_model_path
    from engines.model_library import ModelSpec, format_size
    from quality_settings import _window
    import webbrowser
    window = _window(app, "Set up local translation", colors, center, 560, 400)
    body = tk.Frame(window, bg=colors["bg"], padx=px(24), pady=px(20))
    body.pack(fill="both", expand=True)
    def label(text, **kw):
        widget = tk.Label(body, text=text, bg=colors["bg"], fg=colors["secondary"],
                          wraplength=px(510), justify="left", anchor="w", **kw)
        widget.pack(fill="x", pady=px(5))
        return widget
    label("TranslateGemma 4B", font=("Segoe UI Semibold", 13))
    label("Better translation on this PC for supported languages. A 2.49 GB download that needs 8 GB RAM. Meeting audio and text stay on this PC.")
    accepted = tk.BooleanVar(window)
    tk.Checkbutton(body, text="I accept the Gemma Terms of Use", variable=accepted,
                   **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w")
    ttk.Button(body, text="Read the terms ↗", style="Mac.TButton",
               command=lambda: webbrowser.open(GEMMA_TERMS_URL)).pack(anchor="w")
    folder = tk.StringVar(window, value=str(configured_model_path().parent))
    location = label("")
    def update_location(*_):
        path = Path(folder.get()).expanduser()
        while not path.exists():
            if path == path.parent:
                break
            path = path.parent
        try:
            location.configure(text=f"Save to  {folder.get()} · {format_size(shutil.disk_usage(path).free)} free")
        except OSError:
            location.configure(text="Choose a folder on an available drive.")
    def browse():
        chosen = filedialog.askdirectory(parent=window)
        if chosen:
            folder.set(chosen)
            update_location()
    ttk.Button(body, text="Change…", style="Mac.TButton", command=browse).pack(anchor="e")
    update_location()
    progress = ttk.Progressbar(body, maximum=1, style="Dark.Horizontal.TProgressbar")
    progress.pack(fill="x", pady=px(8))
    status = label("You can close this window. The download keeps going, and Translito tells you when it is ready. Until then, Lite translation is used.")
    current = [next((j for j in app.download_manager.jobs if j.gemma and j.state not in {"Ready", "Cancelled"}), None)]
    def render(job):
        if not window.winfo_exists() or current[0] is not job:
            return
        progress.configure(value=job.fraction)
        status.configure(text=job.error or job.progress_text)
        download.configure(text="Resume download" if job.state == "Paused" else "Continue in background",
                           command=lambda: app.download_manager.resume(job) if job.state == "Paused" else close())
    def start():
        if app.preview_mode:
            status.configure(text="Preview only: no model download starts.")
            return
        if not accepted.get():
            status.configure(text="Review and accept the Gemma Terms of Use first.")
            return
        try:
            path = Path(folder.get()).expanduser()
            if not path.is_absolute():
                raise ValueError("Choose an absolute folder for the model.")
            spec = ModelSpec("gemma", "TranslateGemma", "Translation", MANIFEST["repo"], "gguf",
                             path / MANIFEST["filename"], expected_size=MANIFEST["bytes"])
            current[0] = app.download_manager.enqueue_model(spec, revision=MANIFEST["revision"], gemma=True,
                files=[{"name": MANIFEST["filename"], "size": MANIFEST["bytes"], "sha256": MANIFEST["sha256"]}])
            render(current[0])
        except (ValueError, OSError) as error:
            status.configure(text=str(error))
    buttons = tk.Frame(body, bg=colors["bg"])
    buttons.pack(fill="x", pady=px(8))
    ttk.Button(buttons, text="Cancel download", style="Mac.TButton",
               command=lambda: app.download_manager.cancel(current[0]) if current[0] else close()).pack(side="left")
    download = ttk.Button(buttons, text="Download 2.49 GB", style="Primary.TButton", command=start)
    download.pack(side="right")
    def close():
        if render in app.download_views:
            app.download_views.remove(render)
        window.destroy()
    app.download_views.append(render)
    window.protocol("WM_DELETE_WINDOW", close)
    if current[0]:
        render(current[0])
    return window


def models_page(app, parent, colors):
    from engines.model_library import default_catalog
    from engines.model_files import inspect_model, Ready, Incomplete, Corrupt, model_hint
    heading = tk.Label(parent, text="Models and downloads", bg=colors["bg"], fg=colors["text"], font=("Segoe UI Semibold", 13))
    heading.pack(anchor="w", pady=px((8, 4)))
    tk.Label(parent, text="Models download once, then run on this PC. Downloads continue in the background.",
             bg=colors["bg"], fg=colors["secondary"], wraplength=px(550), justify="left").pack(anchor="w", pady=px((0, 12)))
    rows = {}
    specs = default_catalog()
    for spec in specs:
        row = tk.Frame(parent, bg=colors["surface"], padx=px(12), pady=px(10),
                       highlightthickness=px(1), highlightbackground=colors["border"])
        row.pack(fill="x", pady=px(4))
        tk.Label(row, text=spec.title, bg=colors["surface"], fg=colors["text"]).pack(anchor="w")
        text = tk.StringVar(row)
        tk.Label(row, textvariable=text, bg=colors["surface"], fg=colors["secondary"], wraplength=px(510), justify="left").pack(anchor="w")
        buttons = tk.Frame(row, bg=colors["surface"])
        buttons.pack(fill="x")
        rows[spec.key] = text, buttons
    def refresh(_job=None):
        if not parent.winfo_exists():
            if refresh in app.download_views:
                app.download_views.remove(refresh)
            return
        for spec in specs:
            if _job is not None and _job.repo != spec.repo:
                continue
            text, buttons = rows[spec.key]
            for child in buttons.winfo_children():
                child.destroy()
            job = next((j for j in reversed(app.download_manager.jobs) if j.repo == spec.repo and j.state != "Cancelled"), None)
            def button(title, command):
                ttk.Button(buttons, text=title, style="Mac.TButton", command=command).pack(side="right", padx=px(3))
            if job and job.state != "Ready":
                text.set(job.error or job.progress_text)
                button("Cancel", lambda j=job: app.download_manager.cancel(j))
                if job.state in {"Downloading", "Verifying", "Queued", "Stalled · retrying"}:
                    button("Pause", lambda j=job: app.download_manager.pause(j))
                else:
                    button("Resume", lambda j=job: app.download_manager.resume(j))
                continue
            status = inspect_model(spec)
            text.set("Ready" if isinstance(status, Ready) else
                     "Incomplete" if isinstance(status, Incomplete) else "Corrupt" if isinstance(status, Corrupt) else "Not downloaded")
            if isinstance(status, Ready):
                button("Remove…", app.download_models)
            elif spec.setup:
                button("Set up", app.open_arabic_model_setup if spec.setup == "cohere" else app.open_translation_model_setup)
            else:
                def download(s=spec):
                    try:
                        app.download_manager.enqueue_model(s)
                    except (ValueError, OSError) as error:
                        app.show_hint(str(error))
                button(model_hint(spec, status)[1], download)
    app.download_views.append(refresh)
    refresh()
    tools = tk.Frame(parent, bg=colors["surface"], padx=px(12), pady=px(12))
    tools.pack(fill="x", pady=px(12))
    tk.Label(tools, text="Tools · Compare engines on a sample", bg=colors["surface"], fg=colors["text"]).pack(anchor="w")
    tk.Label(tools, text="Optional. Never needed for setup.", bg=colors["surface"], fg=colors["secondary"]).pack(anchor="w")
    ttk.Button(tools, text="Open", style="Mac.TButton", command=app.open_speed_check).pack(anchor="e")
