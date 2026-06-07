import configparser
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import os
from main import (
    ArabicAudioTranscriber,
    dependency_failure_message,
    load_device_config,
    save_device_config,
    require_dependencies,
    sc,
)


CONFIG_FILE = "config.ini"


LANGUAGES = [
    ("Arabic", "ar-AR", "ar"),
    ("English", "en-US", "en"),
    ("French", "fr-FR", "fr"),
    ("Spanish", "es-ES", "es"),
    ("German", "de-DE", "de"),
    ("Italian", "it-IT", "it"),
    ("Portuguese", "pt-PT", "pt"),
    ("Russian", "ru-RU", "ru"),
    ("Turkish", "tr-TR", "tr"),
    ("Persian", "fa-IR", "fa"),
    ("Urdu", "ur-PK", "ur"),
]


def load_language_config():
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    src = config.get("LANGUAGE", "source", fallback="ar")
    tgt = config.get("LANGUAGE", "target", fallback="en")
    whisper_model = config.get("LANGUAGE", "whisper_model", fallback="openai/whisper-small")
    return src, tgt, whisper_model


def save_language_config(source_code, target_code, whisper_model):
    config = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    if "LANGUAGE" not in config:
        config["LANGUAGE"] = {}
    config["LANGUAGE"]["source"] = source_code
    config["LANGUAGE"]["target"] = target_code
    config["LANGUAGE"]["whisper_model"] = whisper_model
    with open(CONFIG_FILE, "w") as f:
        config.write(f)


def translation_model_for(source_code, target_code):
    return f"Helsinki-NLP/opus-mt-{source_code}-{target_code}"


def whisper_language_for(source_code):
    return source_code


def hide_console_window():
    if os.name != "nt":
        return
    if os.environ.get("GUI_HIDE_CONSOLE", "1").strip() == "0":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def show_startup_error(title, message):
    try:
        error_root = tk.Tk()
        error_root.withdraw()
        messagebox.showerror(title, message)
        error_root.destroy()
    except Exception:
        print(message)


def gui_main():
    failure_message = dependency_failure_message()
    if failure_message:
        show_startup_error("Desktop Audio Translator startup error", failure_message)
        return

    require_dependencies()
    hide_console_window()

    root = tk.Tk()
    root.title("Desktop Audio Translator")

    status_var = tk.StringVar(value="Idle")
    device_var = tk.StringVar(value="")

    src_var = tk.StringVar(value="Arabic")
    tgt_var = tk.StringVar(value="English")
    whisper_var = tk.StringVar(value="openai/whisper-small")
    offline_only_var = tk.BooleanVar(value=False)

    top = ttk.Frame(root, padding=10)
    top.grid(row=0, column=0, sticky="nsew")

    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)
    top.columnconfigure(1, weight=1)

    ttk.Label(top, text="Audio Device").grid(row=0, column=0, sticky="w")
    device_combo = ttk.Combobox(top, textvariable=device_var, state="readonly")
    device_combo.grid(row=0, column=1, sticky="ew", padx=(8, 8))
    btn_refresh = ttk.Button(top, text="Refresh")
    btn_refresh.grid(row=0, column=2, sticky="e")

    ttk.Label(top, text="Speech (source)").grid(row=1, column=0, sticky="w", pady=(10, 0))
    src_combo = ttk.Combobox(top, textvariable=src_var, state="readonly", values=[n for n, _, __ in LANGUAGES])
    src_combo.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))

    ttk.Label(top, text="Translate to").grid(row=2, column=0, sticky="w", pady=(10, 0))
    tgt_combo = ttk.Combobox(top, textvariable=tgt_var, state="readonly", values=[n for n, _, __ in LANGUAGES])
    tgt_combo.grid(row=2, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))

    ttk.Label(top, text="Whisper model").grid(row=3, column=0, sticky="w", pady=(10, 0))
    whisper_combo = ttk.Combobox(
        top,
        textvariable=whisper_var,
        state="readonly",
        values=["openai/whisper-tiny", "openai/whisper-base", "openai/whisper-small", "openai/whisper-medium", "openai/whisper-large-v3"],
    )
    whisper_combo.grid(row=3, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))

    offline_chk = ttk.Checkbutton(top, text="Offline mode (no downloads)", variable=offline_only_var)
    offline_chk.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

    btn_download = ttk.Button(top, text="Download models")
    btn_download.grid(row=4, column=2, sticky="e", pady=(10, 0))

    btn_start = ttk.Button(top, text="Start")
    btn_start.grid(row=5, column=0, sticky="w", pady=(10, 0))

    btn_stop = ttk.Button(top, text="Stop", state="disabled")
    btn_stop.grid(row=5, column=1, sticky="w", pady=(10, 0))

    ttk.Label(top, textvariable=status_var).grid(row=5, column=2, sticky="e", pady=(10, 0))

    text = tk.Text(root, wrap="word")
    text.grid(row=1, column=0, sticky="nsew")

    scrollbar = ttk.Scrollbar(root, orient="vertical", command=text.yview)
    scrollbar.grid(row=1, column=1, sticky="ns")
    text.configure(yscrollcommand=scrollbar.set)

    devices = []
    transcriber_holder = {"obj": None}

    def append_line(line):
        text.insert("end", line + "\n")
        text.see("end")

    def lang_entry_by_name(name):
        for n, bcp47, iso639 in LANGUAGES:
            if n == name:
                return n, bcp47, iso639
        return None

    def refresh_devices():
        nonlocal devices
        try:
            devices = sc.all_microphones(include_loopback=True)
        except Exception as e:
            messagebox.showerror("Error", f"Unable to list devices: {e}")
            devices = []
        display = []
        for d in devices:
            tag = "Loopback" if getattr(d, "isloopback", False) else "Mic"
            display.append(f"{d.name} [{tag}]")
        device_combo["values"] = display

        saved_device_name = load_device_config()
        if saved_device_name:
            for i, d in enumerate(devices):
                if d.name == saved_device_name:
                    device_combo.current(i)
                    break
        if not device_combo.get() and display:
            device_combo.current(0)

    def on_event(event_type, payload):
        def handle():
            if event_type == "status":
                status_var.set(str(payload))
            elif event_type == "error":
                append_line(f"Error: {payload}")
            elif event_type == "transcript":
                try:
                    src_text = payload.get("arabic_text", "")
                    tgt_text = payload.get("english_text", "")
                except Exception:
                    src_text = ""
                    tgt_text = ""
                if src_text:
                    append_line(f"Source: {src_text}")
                if tgt_text:
                    append_line(f"Target: {tgt_text}")
                append_line("-" * 40)
        root.after(0, handle)

    def lock_controls(locked):
        state = "disabled" if locked else "readonly"
        device_combo.configure(state=("disabled" if locked else "readonly"))
        src_combo.configure(state=state)
        tgt_combo.configure(state=state)
        whisper_combo.configure(state=state)
        btn_refresh.configure(state=("disabled" if locked else "normal"))
        btn_download.configure(state=("disabled" if locked else "normal"))
        offline_chk.configure(state=("disabled" if locked else "normal"))
        btn_start.configure(state=("disabled" if locked else "normal"))
        btn_stop.configure(state=("normal" if locked else "disabled"))

    def download_models():
        if transcriber_holder["obj"] is not None:
            return

        src_entry = lang_entry_by_name(src_var.get())
        tgt_entry = lang_entry_by_name(tgt_var.get())
        if not src_entry or not tgt_entry:
            messagebox.showwarning("Language", "Choose source and target languages.")
            return
        _, src_bcp47, src_iso = src_entry
        _, _, tgt_iso = tgt_entry
        model_name = translation_model_for(src_iso, tgt_iso)
        whisper_model = whisper_var.get().strip() or "openai/whisper-small"

        save_language_config(src_iso, tgt_iso, whisper_model)

        def run_download():
            def set_status(s):
                root.after(0, lambda: status_var.set(s))

            lock_controls(True)
            set_status("Downloading")
            try:
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                from transformers import pipeline
                _asr = pipeline("automatic-speech-recognition", model=whisper_model, device=-1)
                _tr = pipeline("translation", model=model_name, device=-1)
                _ = _asr
                _ = _tr
                set_status("Downloaded")
                root.after(0, lambda: append_line(f"Downloaded: {whisper_model} + {model_name}"))
            except Exception as e:
                set_status("Error")
                root.after(0, lambda: messagebox.showerror("Download failed", str(e)))
            finally:
                root.after(0, lambda: lock_controls(False))
                root.after(0, lambda: status_var.set("Idle"))

        threading.Thread(target=run_download, daemon=True).start()

    def start():
        if transcriber_holder["obj"] is not None:
            return

        idx = device_combo.current()
        if idx < 0 or idx >= len(devices):
            messagebox.showwarning("Device", "Select an audio device first.")
            return
        selected = devices[idx]
        save_device_config(selected.name)

        src_entry = lang_entry_by_name(src_var.get())
        tgt_entry = lang_entry_by_name(tgt_var.get())
        if not src_entry or not tgt_entry:
            messagebox.showwarning("Language", "Choose source and target languages.")
            return
        if src_entry[2] == tgt_entry[2]:
            messagebox.showwarning("Language", "Source and target languages must be different.")
            return

        _, src_bcp47, src_iso = src_entry
        _, _, tgt_iso = tgt_entry
        whisper_model = whisper_var.get().strip() or "openai/whisper-small"
        translation_model = translation_model_for(src_iso, tgt_iso)

        save_language_config(src_iso, tgt_iso, whisper_model)

        if offline_only_var.get():
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            os.environ["OFFLINE_ONLY"] = "1"
        else:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            os.environ["OFFLINE_ONLY"] = "0"

        append_line(f"Device: {selected.name}")
        append_line(f"Speech: {src_var.get()}  →  Translate to: {tgt_var.get()}")
        append_line(f"Models: {whisper_model} + {translation_model}")

        try:
            transcriber = ArabicAudioTranscriber(
                selected_device=selected,
                on_event=on_event,
                interactive=False,
                asr_language=src_bcp47,
                translation_model=translation_model,
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start: {e}")
            return

        transcriber_holder["obj"] = transcriber
        lock_controls(True)
        status_var.set("Running")
        transcriber.start_background(enable_keyboard_shortcuts=False)

    def stop():
        transcriber = transcriber_holder["obj"]
        if transcriber is None:
            return
        status_var.set("Stopping")
        transcriber.stop_background()

        def finalize():
            transcriber.join_background()
            transcriber.save_transcript()
            transcriber_holder["obj"] = None
            root.after(0, lambda: lock_controls(False))
            root.after(0, lambda: status_var.set("Idle"))

        threading.Thread(target=finalize, daemon=True).start()

    def on_close():
        if transcriber_holder["obj"] is not None:
            stop()
        root.after(300, root.destroy)

    btn_refresh.configure(command=refresh_devices)
    btn_download.configure(command=download_models)
    btn_start.configure(command=start)
    btn_stop.configure(command=stop)
    root.protocol("WM_DELETE_WINDOW", on_close)

    src_iso, tgt_iso, whisper_model = load_language_config()
    for n, _, iso in LANGUAGES:
        if iso == src_iso:
            src_var.set(n)
            break
    for n, _, iso in LANGUAGES:
        if iso == tgt_iso:
            tgt_var.set(n)
            break
    whisper_var.set(whisper_model)

    refresh_devices()
    root.mainloop()


if __name__ == "__main__":
    gui_main()
