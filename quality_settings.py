"""Local model setup and Terms editor, using the app's Tk style."""
from pathlib import Path
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from app_config import CONFIG_FILE, load_cohere_cache_dir, save_cohere_cache_dir
from engines.asr_cohere_local import MODEL_TERMS_URL
from engines.display import display_text
from engines.glossary import Glossary


def _window(app, title, colors, center, width, height):
    window = tk.Toplevel(app.root)
    window.title(title)
    window.configure(bg=colors["bg"])
    window.transient(app.root)
    window.minsize(width, height)
    center(window, app.settings_window or app.root, width=width, height=height)
    return window


def _entry(parent, label, variable, colors, *, secret=False):
    row = tk.Frame(parent, bg=colors["bg"])
    row.pack(fill="x", pady=5)
    tk.Label(row, text=label, bg=colors["bg"], fg=colors["text"], anchor="w", width=17).pack(side="left")
    field = tk.Entry(row, textvariable=variable, show="•" if secret else "", bg=colors["field"],
                     fg=colors["text"], insertbackground=colors["text"], relief="flat")
    field.pack(side="left", fill="x", expand=True, ipady=6)
    return field


def open_cohere_setup(app, colors, center):
    window = _window(app, "Set up Saudi Arabic recognition", colors, center, 600, 510)
    body = tk.Frame(window, bg=colors["bg"], padx=18, pady=18)
    body.pack(fill="both", expand=True)
    tk.Label(body, text="Cohere Transcribe Arabic", bg=colors["bg"], fg=colors["text"],
             font=("Segoe UI Semibold", 12), anchor="w").pack(fill="x")
    tk.Label(body, text="Recommended for Saudi Arabic and English in the same conversation. "
             "It runs on your PC. Downloading the model does not upload meeting audio.",
             bg=colors["bg"], fg=colors["secondary"], wraplength=555, justify="left").pack(fill="x", pady=8)
    ttk.Button(body, text="1. Review and accept the Hugging Face model conditions", style="Mac.TButton",
               command=lambda: webbrowser.open(MODEL_TERMS_URL)).pack(anchor="w", pady=5)
    accepted = tk.BooleanVar(value=False)
    tk.Checkbutton(body, text="I accepted the model conditions on Hugging Face", variable=accepted,
                    **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=5)
    key, folder, status = tk.StringVar(), tk.StringVar(), tk.StringVar(value="Read tokens are saved only in Windows Credential Manager.")
    cache = load_cohere_cache_dir() or str(CONFIG_FILE.parent / "models" / "cohere")
    # The user sees and can change this path before an explicit download.
    if not load_cohere_cache_dir() and Path("D:/").exists() and shutil.disk_usage(Path("D:/")).free > 8 * 2**30:
        cache = "D:/TranslitoModels/cohere"
    folder.set(cache)
    _entry(body, "2. HF read token", key, colors, secret=True)
    _entry(body, "Model folder", folder, colors)
    buttons = tk.Frame(body, bg=colors["bg"])
    buttons.pack(fill="x", pady=6)

    def browse():
        selected = filedialog.askdirectory(parent=window, title="Choose model cache folder")
        if selected:
            folder.set(selected)

    ttk.Button(buttons, text="Choose folder", style="Mac.TButton", command=browse).pack(side="left")

    def download():
        if app.transcriber is not None:
            status.set("Stop the current session before downloading a model.")
            return
        if app.preview_mode:
            status.set("Preview only: no key is saved and no download starts.")
            return
        if not accepted.get():
            messagebox.showinfo("Model conditions", "Review and accept the model conditions first.", parent=window)
            return
        try:
            from engines.secrets import CredentialStore
            credentials = CredentialStore()
            if key.get().strip():
                credentials.save("huggingface", key.get())
                key.set("")
            if not credentials.get("huggingface"):
                raise ValueError("Paste your Hugging Face read token.")
            chosen = Path(folder.get()).expanduser()
            if not chosen.is_absolute():
                raise ValueError("Choose an absolute folder for the model.")
            existing = chosen
            while not existing.exists():
                if existing.parent == existing:
                    raise ValueError("Choose a folder on an available drive.")
                existing = existing.parent
            if shutil.disk_usage(existing).free < 8 * 2**30:
                raise ValueError("Choose a model folder with at least 8 GB of free disk space.")
            save_cohere_cache_dir(chosen)
        except Exception as exc:
            status.set(str(exc))
            return
        download_button.configure(state="disabled")
        fallback_button.configure(state="disabled")
        status.set("Downloading and preparing the model…")
        app.model_setup_busy = True
        app.set_status("Loading models")
        app.update_action_button(running=False, loading=True)

        def work():
            success = False
            try:
                import torch
                from engines.asr_local import get_cohere_model
                model = get_cohere_model(device="cuda:0" if torch.cuda.is_available() else "cpu",
                                          cache_dir=str(chosen), on_event=app.on_event)
                model.offline_only = False
                model.credentials = credentials
                try:
                    model.load()
                finally:
                    model.offline_only = True
                success = True
            except Exception:
                # Download SDK errors may contain auth information; never show
                # their exception text or traceback in this provider card.
                pass

            def finish():
                app.model_setup_busy = False
                app.finish_model_progress()
                app.set_status("Ready")
                app.update_action_button(running=False)
                if window.winfo_exists():
                    download_button.configure(state="normal")
                    fallback_button.configure(state="normal")
                    status.set("Model ready. Your next Arabic/English session will use it." if success else
                               "Model setup failed. Check model access, the read token and free disk space, then retry.")

            try:
                app.root.after(0, finish)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=work, daemon=True).start()

    download_button = ttk.Button(buttons, text="3. Save key and download", style="Primary.TButton", command=download)
    download_button.pack(side="right")
    tk.Label(body, textvariable=status, bg=colors["bg"], fg=colors["secondary"], wraplength=550,
             justify="left", anchor="w").pack(fill="x", pady=8)
    tk.Label(body, text="Lower-memory alternative: an Arabic/English Whisper model tuned on Egyptian speech. "
             "It needs no Hugging Face token, but may be weaker on Saudi dialects.", bg=colors["bg"],
             fg=colors["secondary"], wraplength=550, justify="left").pack(fill="x", pady=(10, 5))

    def download_fallback():
        if app.preview_mode or app.transcriber is not None:
            status.set("Stop the session to download. Preview mode does not download models.")
            return
        try:
            chosen = Path(folder.get()).expanduser()
            save_cohere_cache_dir(chosen)
        except Exception:
            status.set("Choose an absolute model folder with enough free disk space.")
            return
        fallback_button.configure(state="disabled")
        download_button.configure(state="disabled")
        app.set_status("Loading models")
        app.update_action_button(running=False, loading=True)
        status.set("Downloading the Arabic/English fallback…")
        app.model_setup_busy = True

        def work():
            success = False
            try:
                from engines.asr_codeswitch import prepare_codeswitch_model
                prepare_codeswitch_model(on_event=app.on_event)
                success = True
            except Exception:
                pass

            def finish():
                app.model_setup_busy = False
                app.finish_model_progress()
                app.set_status("Ready")
                app.update_action_button(running=False)
                if window.winfo_exists():
                    fallback_button.configure(state="normal")
                    download_button.configure(state="normal")
                    status.set("Fallback ready. It will be used when Cohere Arabic is unavailable." if success else
                               "Fallback setup failed. Check your connection and free disk space, then retry.")

            try:
                app.root.after(0, finish)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=work, daemon=True).start()

    fallback_button = ttk.Button(body, text="Download the Arabic/English fallback", style="Mac.TButton",
                                  command=download_fallback)
    fallback_button.pack(anchor="w")
    return window


def open_terms_editor(app, colors, center):
    path = Path(tempfile.gettempdir()) / "Translito-preview" / "glossary.json" if app.preview_mode else None
    glossary = Glossary(path)
    window = _window(app, "Terms", colors, center, 800, 560)
    body = tk.Frame(window, bg=colors["bg"], padx=16, pady=16)
    body.pack(fill="both", expand=True)
    tk.Label(body, text="English terms and Arabic spellings", bg=colors["bg"], fg=colors["text"],
             font=("Segoe UI Semibold", 12), anchor="w").pack(fill="x")
    tk.Label(body, text="Terms guide recognition and translation. Disabling a term preserves it in your glossary.",
             bg=colors["bg"], fg=colors["secondary"], anchor="w").pack(fill="x", pady=(4, 10))
    table_host = tk.Frame(body, bg=colors["bg"])
    table_host.pack(fill="both", expand=True)
    app.style.configure("Terms.Treeview", background=colors["field"], fieldbackground=colors["field"],
                        foreground=colors["text"], rowheight=26, borderwidth=0)
    app.style.map("Terms.Treeview", background=[("selected", colors["blue"])])
    tree = ttk.Treeview(table_host, columns=("english", "spellings", "translation"),
                        show="headings", style="Terms.Treeview", selectmode="browse")
    for column, title, width in (("english", "English term", 180), ("spellings", "Arabic spellings", 300),
                                  ("translation", "Preferred Arabic translation", 220)):
        tree.heading(column, text=title)
        tree.column(column, width=width, anchor="e" if column != "english" else "w")
    scroll = ttk.Scrollbar(table_host, orient="vertical", command=tree.yview, style="Dark.Vertical.TScrollbar")
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    english, spellings, translation, status = (tk.StringVar() for _ in range(4))
    selected = [None]
    _entry(body, "English term", english, colors)
    _entry(body, "Arabic spellings", spellings, colors)
    _entry(body, "Arabic translation", translation, colors)

    def refresh():
        tree.delete(*tree.get_children())
        for index, term in enumerate(glossary.data["terms"]):
            if not term.get("disabled"):
                tree.insert("", "end", iid=str(index), values=(term["english"],
                    display_text(", ".join(term.get("spellings", []))), display_text(term.get("arabic_translation", ""))))

    def select(_event=None):
        if tree.selection():
            index = int(tree.selection()[0])
            term = glossary.data["terms"][index]
            selected[0] = index
            english.set(term["english"])
            spellings.set(", ".join(term.get("spellings", [])))
            translation.set(term.get("arabic_translation", ""))

    tree.bind("<<TreeviewSelect>>", select)

    def add():
        selected[0] = None
        english.set("")
        spellings.set("")
        translation.set("")

    def save():
        import copy
        term = english.get().strip()
        if not term:
            status.set("Enter an English term.")
            return
        duplicate = next((i for i, value in enumerate(glossary.data["terms"])
                          if value["english"].casefold() == term.casefold()), None)
        if duplicate is not None and duplicate != selected[0]:
            status.set("That term already exists. Select it in the table to edit it.")
            return
        value = {"english": term, "spellings": [s.strip() for s in spellings.get().replace("،", ",").split(",") if s.strip()],
                 "arabic_translation": translation.get().strip(), "disabled": False}
        previous = copy.deepcopy(glossary.data["terms"])
        if selected[0] is None:
            glossary.data["terms"].append(value)
        else:
            glossary.data["terms"][selected[0]].update(value)
        try:
            glossary.save()
        except (OSError, ValueError):
            glossary.data["terms"] = previous
            status.set("Could not save the glossary. Its existing file was preserved.")
            return
        refresh()
        add()
        status.set("Term saved. It applies to your next session.")

    def disable():
        if selected[0] is not None:
            record = glossary.data["terms"][selected[0]]
            previous = record.get("disabled", False)
            record["disabled"] = True
            try:
                glossary.save()
            except (OSError, ValueError):
                record["disabled"] = previous
                status.set("Could not save the glossary. Its existing file was preserved.")
                return
            refresh()
            add()
            status.set("Term disabled and preserved in the glossary.")

    buttons = tk.Frame(body, bg=colors["bg"])
    buttons.pack(fill="x", pady=8)
    for text, command in (("Add term", add), ("Save term", save), ("Disable term", disable)):
        ttk.Button(buttons, text=text, style="Mac.TButton", command=command).pack(side="left", padx=(0, 8))
    tk.Label(body, textvariable=status, bg=colors["bg"], fg=colors["secondary"], anchor="w").pack(fill="x")
    refresh()
    return window
