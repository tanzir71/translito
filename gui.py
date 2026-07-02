import os
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

from app_config import (
    DEFAULT_HOTKEYS,
    load_device_config,
    load_hotkey_config,
    load_language_config,
    load_runtime_config,
    load_speak_config,
    save_device_config,
    save_hotkey_config,
    save_language_config,
    save_runtime_config,
    save_speak_config,
)
from device_utils import (
    conference_mic_hint,
    first_real_microphone,
    first_virtual_output,
    query_input_devices,
    query_output_devices,
    same_physical_device,
)
from hotkeys import GlobalHotkeyManager, format_tk_key_event
from login import is_open_at_login_enabled, set_open_at_login
from main import ArabicAudioTranscriber, dependency_failure_message, require_dependencies, torch
from model_loading import GLOBAL_MODEL_MANAGER
from speech_output import LocalSpeechSynthesizer


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

WHISPER_MODELS = [
    "openai/whisper-tiny",
    "openai/whisper-base",
    "openai/whisper-small",
    "openai/whisper-medium",
    "openai/whisper-large-v3",
]

HOTKEY_LABELS = {
    "toggle": "Toggle",
    "listen": "Start Listen",
    "speak": "Start Speak",
    "stop": "Stop",
}


def translation_model_for(source_code, target_code):
    return f"Helsinki-NLP/opus-mt-{source_code}-{target_code}"


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


class TranslatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Desktop Audio Translator")
        self.root.geometry("920x680")

        self.input_choices = []
        self.listen_choices = []
        self.speak_mic_choices = []
        self.output_choices = []
        self.transcriber = None
        self.recording_action = None
        self.synthesizer = LocalSpeechSynthesizer()

        language_config = load_language_config(CONFIG_FILE)
        speak_config = load_speak_config(CONFIG_FILE)
        runtime_config = load_runtime_config(CONFIG_FILE)
        hotkeys = load_hotkey_config(CONFIG_FILE)

        self.mode_var = tk.StringVar(value=runtime_config.last_mode)
        self.listen_device_var = tk.StringVar(value="")
        self.speak_mic_var = tk.StringVar(value=speak_config.mic_name)
        self.speak_output_var = tk.StringVar(value=speak_config.output_device_name)
        self.listen_source_var = tk.StringVar(value=self.language_name_for_iso(language_config.source))
        self.listen_target_var = tk.StringVar(value=self.language_name_for_iso(language_config.target))
        self.speak_source_var = tk.StringVar(value=self.language_name_for_iso(speak_config.source))
        self.speak_target_var = tk.StringVar(value=self.language_name_for_iso(speak_config.target))
        self.whisper_var = tk.StringVar(value=language_config.whisper_model)
        self.offline_only_var = tk.BooleanVar(value=False)
        self.monitor_var = tk.BooleanVar(value=speak_config.monitor_spoken_audio)
        self.voice_var = tk.StringVar(value=speak_config.voice or "Automatic")
        self.noise_gate_var = tk.DoubleVar(value=runtime_config.mic_noise_gate)
        self.status_var = tk.StringVar(value="Ready")
        self.phase_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)
        self.routing_var = tk.StringVar(value="")
        self.login_var = tk.BooleanVar(value=is_open_at_login_enabled())
        self.hotkey_vars = {
            action: tk.StringVar(value=hotkeys.get(action, default))
            for action, default in DEFAULT_HOTKEYS.items()
        }

        self.build_ui()
        self.bind_events()

        self.hotkey_manager = GlobalHotkeyManager(
            callbacks={
                "toggle": lambda: self.root.after(0, self.hotkey_toggle),
                "listen": lambda: self.root.after(0, lambda: self.hotkey_start_mode("listen")),
                "speak": lambda: self.root.after(0, lambda: self.hotkey_start_mode("speak")),
                "stop": lambda: self.root.after(0, self.stop),
            },
            on_error=lambda message: self.root.after(
                0, lambda message=message: self.append_line(f"Hotkey error: {message}")
            ),
        )
        self.register_hotkeys()

        self.refresh_devices(show_error=True)
        self.update_mode_visibility()
        self.update_routing_banner()
        self.refresh_voices()
        self.root.after(250, self.preload_current_models)
        self.root.after(3000, self.auto_refresh_devices)

    def build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=1)

        ttk.Label(top, text="Mode").grid(row=0, column=0, sticky="w")
        mode_frame = ttk.Frame(top)
        mode_frame.grid(row=0, column=1, columnspan=3, sticky="w")
        ttk.Radiobutton(
            mode_frame,
            text="Translate Audio",
            value="listen",
            variable=self.mode_var,
            command=self.update_mode_visibility,
        ).grid(row=0, column=0, padx=(0, 12))
        ttk.Radiobutton(
            mode_frame,
            text="Speak Translation",
            value="speak",
            variable=self.mode_var,
            command=self.update_mode_visibility,
        ).grid(row=0, column=1)
        self.btn_refresh = ttk.Button(top, text="Refresh", command=lambda: self.refresh_devices(show_error=True))
        self.btn_refresh.grid(row=0, column=4, sticky="e")

        self.listen_frame = ttk.LabelFrame(top, text="Translate Audio", padding=8)
        self.listen_frame.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        self.listen_frame.columnconfigure(1, weight=1)
        self.listen_frame.columnconfigure(3, weight=1)
        ttk.Label(self.listen_frame, text="Audio device").grid(row=0, column=0, sticky="w")
        self.listen_combo = ttk.Combobox(self.listen_frame, textvariable=self.listen_device_var, state="readonly")
        self.listen_combo.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))
        ttk.Label(self.listen_frame, text="Speech").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.listen_source_combo = ttk.Combobox(
            self.listen_frame,
            textvariable=self.listen_source_var,
            state="readonly",
            values=[name for name, _bcp47, _iso in LANGUAGES],
        )
        self.listen_source_combo.grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        ttk.Label(self.listen_frame, text="Translate to").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.listen_target_combo = ttk.Combobox(
            self.listen_frame,
            textvariable=self.listen_target_var,
            state="readonly",
            values=[name for name, _bcp47, _iso in LANGUAGES],
        )
        self.listen_target_combo.grid(row=1, column=3, sticky="ew", pady=(8, 0))

        self.speak_frame = ttk.LabelFrame(top, text="Speak Translation", padding=8)
        self.speak_frame.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        self.speak_frame.columnconfigure(1, weight=1)
        self.speak_frame.columnconfigure(3, weight=1)
        ttk.Label(self.speak_frame, text="Microphone").grid(row=0, column=0, sticky="w")
        self.speak_mic_combo = ttk.Combobox(self.speak_frame, textvariable=self.speak_mic_var, state="readonly")
        self.speak_mic_combo.grid(row=0, column=1, sticky="ew", padx=(8, 16))
        ttk.Label(self.speak_frame, text="Speak to").grid(row=0, column=2, sticky="w")
        self.speak_output_combo = ttk.Combobox(self.speak_frame, textvariable=self.speak_output_var, state="readonly")
        self.speak_output_combo.grid(row=0, column=3, sticky="ew")
        ttk.Label(self.speak_frame, text="Speech").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.speak_source_combo = ttk.Combobox(
            self.speak_frame,
            textvariable=self.speak_source_var,
            state="readonly",
            values=[name for name, _bcp47, _iso in LANGUAGES],
        )
        self.speak_source_combo.grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        ttk.Label(self.speak_frame, text="Speak as").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.speak_target_combo = ttk.Combobox(
            self.speak_frame,
            textvariable=self.speak_target_var,
            state="readonly",
            values=[name for name, _bcp47, _iso in LANGUAGES],
        )
        self.speak_target_combo.grid(row=1, column=3, sticky="ew", pady=(8, 0))
        ttk.Label(self.speak_frame, text="Voice").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.voice_combo = ttk.Combobox(self.speak_frame, textvariable=self.voice_var, state="readonly")
        self.voice_combo.grid(row=2, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        self.monitor_check = ttk.Checkbutton(self.speak_frame, text="Monitor", variable=self.monitor_var)
        self.monitor_check.grid(row=2, column=2, sticky="w", pady=(8, 0))
        self.routing_label = ttk.Label(self.speak_frame, textvariable=self.routing_var, wraplength=760)
        self.routing_label.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        settings = ttk.LabelFrame(top, text="Settings", padding=8)
        settings.grid(row=3, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        ttk.Label(settings, text="Whisper model").grid(row=0, column=0, sticky="w")
        self.whisper_combo = ttk.Combobox(settings, textvariable=self.whisper_var, state="readonly", values=WHISPER_MODELS)
        self.whisper_combo.grid(row=0, column=1, sticky="ew", padx=(8, 16))
        self.offline_check = ttk.Checkbutton(settings, text="Offline mode", variable=self.offline_only_var)
        self.offline_check.grid(row=0, column=2, sticky="w")
        self.btn_download = ttk.Button(settings, text="Download models", command=self.download_models)
        self.btn_download.grid(row=0, column=3, sticky="e")

        ttk.Label(settings, text="Mic noise gate").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.noise_gate_scale = ttk.Scale(
            settings,
            from_=0.0,
            to=0.008,
            variable=self.noise_gate_var,
            command=lambda _value: self.update_noise_gate_label(),
        )
        self.noise_gate_scale.grid(row=1, column=1, sticky="ew", padx=(8, 16), pady=(8, 0))
        self.noise_gate_label = ttk.Label(settings, text="")
        self.noise_gate_label.grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.login_check = ttk.Checkbutton(
            settings,
            text="Open at login",
            variable=self.login_var,
            command=self.toggle_login,
        )
        self.login_check.grid(row=1, column=3, sticky="e", pady=(8, 0))

        hotkeys = ttk.LabelFrame(top, text="Hotkeys", padding=8)
        hotkeys.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        for column in range(4):
            hotkeys.columnconfigure(column, weight=1)
        for index, action in enumerate(("toggle", "listen", "speak", "stop")):
            ttk.Label(hotkeys, text=HOTKEY_LABELS[action]).grid(row=index, column=0, sticky="w")
            entry = ttk.Entry(hotkeys, textvariable=self.hotkey_vars[action], width=18)
            entry.grid(row=index, column=1, sticky="w", padx=(8, 8), pady=(2, 2))
            ttk.Button(hotkeys, text="Record", command=lambda a=action: self.record_hotkey(a)).grid(
                row=index, column=2, sticky="w", padx=(0, 8), pady=(2, 2)
            )
            ttk.Button(hotkeys, text="Clear", command=lambda a=action: self.clear_hotkey(a)).grid(
                row=index, column=3, sticky="w", pady=(2, 2)
            )
        ttk.Button(hotkeys, text="Reset defaults", command=self.reset_hotkeys).grid(row=0, column=4, sticky="e")

        controls = ttk.Frame(top)
        controls.grid(row=5, column=0, columnspan=5, sticky="ew", pady=(8, 0))
        controls.columnconfigure(4, weight=1)
        self.btn_start = ttk.Button(controls, text="Start", command=self.start)
        self.btn_start.grid(row=0, column=0, sticky="w")
        self.btn_stop = ttk.Button(controls, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=2, sticky="w", padx=(16, 8))
        self.progress = ttk.Progressbar(controls, variable=self.progress_var, maximum=100, length=160)
        self.progress.grid(row=0, column=3, sticky="w")
        ttk.Label(controls, textvariable=self.phase_var).grid(row=0, column=4, sticky="ew", padx=(8, 0))

        body = ttk.Frame(self.root)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.text = tk.Text(body, wrap="word")
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scrollbar.set)

        self.update_noise_gate_label()

    def bind_events(self):
        self.listen_combo.bind("<<ComboboxSelected>>", lambda _event: self.persist_current_listen_device())
        self.speak_output_combo.bind("<<ComboboxSelected>>", lambda _event: self.update_routing_banner())
        self.speak_target_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_voices())
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def language_name_for_iso(self, iso):
        for name, _bcp47, language_iso in LANGUAGES:
            if language_iso == iso:
                return name
        return "English"

    def language_entry_by_name(self, name):
        for entry in LANGUAGES:
            if entry[0] == name:
                return entry
        return LANGUAGES[0]

    def selected_listen_choice(self):
        index = self.listen_combo.current()
        if 0 <= index < len(self.listen_choices):
            return self.listen_choices[index]
        return self.listen_choices[0] if self.listen_choices else None

    def selected_speak_mic_choice(self):
        index = self.speak_mic_combo.current()
        if 0 <= index < len(self.speak_mic_choices):
            return self.speak_mic_choices[index]
        return self.speak_mic_choices[0] if self.speak_mic_choices else None

    def selected_output_choice(self):
        index = self.speak_output_combo.current()
        if 0 <= index < len(self.output_choices):
            return self.output_choices[index]
        return None

    def refresh_devices(self, show_error=False):
        current_listen = self.selected_listen_choice()
        listen_name = current_listen.name if current_listen else load_device_config(CONFIG_FILE)
        current_mic = self.selected_speak_mic_choice()
        mic_name = current_mic.name if current_mic else self.speak_mic_var.get()
        current_output = self.selected_output_choice()
        output_name = current_output.name if current_output else self.speak_output_var.get()

        try:
            self.input_choices = query_input_devices(include_loopback=True)
            self.output_choices = query_output_devices()
        except Exception as exc:
            if show_error:
                messagebox.showerror("Devices", f"Unable to list devices: {exc}")
            return

        self.listen_choices = self.input_choices
        self.speak_mic_choices = [
            choice for choice in self.input_choices if not choice.is_loopback and not choice.is_virtual
        ]
        if not self.speak_mic_choices:
            self.speak_mic_choices = [choice for choice in self.input_choices if not choice.is_loopback]
        if not self.speak_mic_choices:
            self.speak_mic_choices = self.input_choices

        self.listen_combo["values"] = [choice.display_name for choice in self.listen_choices]
        self.speak_mic_combo["values"] = [choice.display_name for choice in self.speak_mic_choices]
        self.speak_output_combo["values"] = [choice.display_name for choice in self.output_choices]

        self.select_combo_by_name(self.listen_combo, self.listen_choices, listen_name)
        fallback_mic = first_real_microphone(self.speak_mic_choices)
        self.select_combo_by_name(self.speak_mic_combo, self.speak_mic_choices, mic_name, fallback_mic)
        fallback_output = first_virtual_output(self.output_choices)
        self.select_combo_by_name(self.speak_output_combo, self.output_choices, output_name, fallback_output)
        self.update_routing_banner()

    def select_combo_by_name(self, combo, choices, name, fallback=None):
        if not choices:
            combo.set("")
            return
        for index, choice in enumerate(choices):
            if choice.name == name:
                combo.current(index)
                return
        if fallback is not None and fallback in choices:
            combo.current(choices.index(fallback))
        else:
            combo.current(0)

    def auto_refresh_devices(self):
        if self.transcriber is None:
            self.refresh_devices(show_error=False)
        self.root.after(3000, self.auto_refresh_devices)

    def update_mode_visibility(self):
        if self.mode_var.get() == "speak":
            self.listen_frame.grid_remove()
            self.speak_frame.grid()
        else:
            self.speak_frame.grid_remove()
            self.listen_frame.grid()

    def update_routing_banner(self):
        output = self.selected_output_choice()
        output_name = output.name if output else ""
        self.routing_var.set(conference_mic_hint(output_name))

    def update_noise_gate_label(self):
        value = float(self.noise_gate_var.get())
        if value <= 0:
            label = "Off"
        elif value < 0.0015:
            label = "Low"
        elif value < 0.003:
            label = "Medium"
        else:
            label = "High"
        self.noise_gate_label.configure(text=f"{label} ({value:.4f})")

    def refresh_voices(self):
        _name, _bcp47, target_iso = self.language_entry_by_name(self.speak_target_var.get())
        voices = self.synthesizer.available_voices(target_iso)
        self.voice_combo["values"] = voices
        if self.voice_var.get() not in voices:
            self.voice_var.set("Automatic")

    def persist_current_listen_device(self):
        choice = self.selected_listen_choice()
        if choice:
            save_device_config(choice.name, CONFIG_FILE)

    def configure_offline_env(self):
        if self.offline_only_var.get():
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            os.environ["OFFLINE_ONLY"] = "1"
        else:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            os.environ["OFFLINE_ONLY"] = "0"

    def current_model_request(self):
        mode = self.mode_var.get()
        if mode == "speak":
            _src_name, src_bcp47, src_iso = self.language_entry_by_name(self.speak_source_var.get())
            _tgt_name, _tgt_bcp47, tgt_iso = self.language_entry_by_name(self.speak_target_var.get())
        else:
            _src_name, src_bcp47, src_iso = self.language_entry_by_name(self.listen_source_var.get())
            _tgt_name, _tgt_bcp47, tgt_iso = self.language_entry_by_name(self.listen_target_var.get())
        return {
            "mode": mode,
            "src_bcp47": src_bcp47,
            "src_iso": src_iso,
            "tgt_iso": tgt_iso,
            "whisper_model": self.whisper_var.get().strip() or "openai/whisper-small",
            "translation_model": translation_model_for(src_iso, tgt_iso),
        }

    def start(self):
        if self.transcriber is not None:
            return
        request = self.current_model_request()
        if request["src_iso"] == request["tgt_iso"]:
            messagebox.showwarning("Language", "Source and target languages must be different.")
            return

        self.configure_offline_env()
        self.update_noise_gate_label()
        mic_noise_gate = float(self.noise_gate_var.get())
        save_runtime_config(CONFIG_FILE, mic_noise_gate=mic_noise_gate, last_mode=request["mode"])

        if request["mode"] == "speak":
            mic_choice = self.selected_speak_mic_choice()
            output_choice = self.selected_output_choice()
            if mic_choice is None:
                messagebox.showwarning("Microphone", "Select a microphone first.")
                return
            if output_choice and not output_choice.is_virtual and same_physical_device(mic_choice.name, output_choice.name):
                messagebox.showwarning("Routing", "Choose a different output device for Speak Mode.")
                return
            selected_device = mic_choice.raw
            output_name = output_choice.name if output_choice else ""
            save_speak_config(
                CONFIG_FILE,
                source=request["src_iso"],
                target=request["tgt_iso"],
                mic_name=mic_choice.name,
                output_device_name=output_name,
                voice=self.voice_var.get(),
                monitor_spoken_audio=self.monitor_var.get(),
            )
        else:
            listen_choice = self.selected_listen_choice()
            if listen_choice is None:
                messagebox.showwarning("Device", "Select an audio device first.")
                return
            selected_device = listen_choice.raw
            output_name = ""
            save_device_config(listen_choice.name, CONFIG_FILE)
            save_language_config(
                request["src_iso"],
                request["tgt_iso"],
                request["whisper_model"],
                CONFIG_FILE,
            )

        self.append_line(f"Mode: {request['mode']}")
        self.append_line(f"Models: {request['whisper_model']} + {request['translation_model']}")
        self.lock_controls(True)
        self.status_var.set("Loading models")

        def run_start():
            try:
                transcriber = ArabicAudioTranscriber(
                    selected_device=selected_device,
                    on_event=self.on_event,
                    interactive=False,
                    asr_language=request["src_bcp47"],
                    translation_model=request["translation_model"],
                    mode=request["mode"],
                    target_language=request["tgt_iso"],
                    speech_output_device_name=output_name,
                    speech_voice=self.voice_var.get(),
                    monitor_spoken_audio=self.monitor_var.get(),
                    mic_noise_gate=mic_noise_gate,
                )
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self.start_failed(exc))
                return

            def finish_start():
                self.transcriber = transcriber
                self.status_var.set("Listening")
                self.phase_var.set("")
                self.progress.stop()
                self.progress.configure(mode="determinate")
                self.progress_var.set(0)
                transcriber.start_background(enable_keyboard_shortcuts=False)

            self.root.after(0, finish_start)

        threading.Thread(target=run_start, daemon=True).start()

    def start_failed(self, exc):
        self.lock_controls(False)
        self.status_var.set("Error")
        messagebox.showerror("Start failed", str(exc))

    def stop(self, after=None):
        transcriber = self.transcriber
        if transcriber is None:
            if callable(after):
                after()
            return
        self.status_var.set("Stopping")
        transcriber.stop_background()

        def finalize():
            transcriber.join_background()
            transcriber.save_transcript()

            def done():
                self.transcriber = None
                self.lock_controls(False)
                self.status_var.set("Ready")
                if callable(after):
                    after()

            self.root.after(0, done)

        threading.Thread(target=finalize, daemon=True).start()

    def hotkey_toggle(self):
        if self.transcriber is None:
            last_mode = load_runtime_config(CONFIG_FILE).last_mode
            self.mode_var.set(last_mode)
            self.update_mode_visibility()
            self.start()
        elif self.mode_var.get() == "listen":
            self.hotkey_start_mode("speak")
        else:
            self.hotkey_start_mode("listen")

    def hotkey_start_mode(self, mode):
        if self.transcriber is None:
            self.mode_var.set(mode)
            self.update_mode_visibility()
            self.start()
            return
        if self.mode_var.get() == mode:
            return
        self.stop(after=lambda: (self.mode_var.set(mode), self.update_mode_visibility(), self.start()))

    def lock_controls(self, locked):
        combo_state = "disabled" if locked else "readonly"
        normal_state = "disabled" if locked else "normal"
        for widget in (
            self.listen_combo,
            self.listen_source_combo,
            self.listen_target_combo,
            self.speak_mic_combo,
            self.speak_output_combo,
            self.speak_source_combo,
            self.speak_target_combo,
            self.voice_combo,
            self.whisper_combo,
        ):
            widget.configure(state=combo_state)
        for widget in (
            self.btn_refresh,
            self.btn_download,
            self.offline_check,
            self.monitor_check,
            self.noise_gate_scale,
            self.login_check,
        ):
            widget.configure(state=normal_state)
        self.btn_start.configure(state="disabled" if locked else "normal")
        self.btn_stop.configure(state="normal" if locked else "disabled")

    def on_event(self, event_type, payload):
        def handle():
            if event_type == "status":
                self.status_var.set(self.pretty_status(str(payload)))
            elif event_type == "model_progress":
                self.handle_model_progress(payload or {})
            elif event_type == "hint":
                self.append_line(str(payload))
            elif event_type == "error":
                self.append_line(f"Error: {payload}")
            elif event_type == "transcript":
                source_text = payload.get("source_text", payload.get("arabic_text", ""))
                translated_text = payload.get("translated_text", payload.get("english_text", ""))
                if source_text:
                    self.append_line(f"Source: {source_text}")
                if translated_text:
                    self.append_line(f"Target: {translated_text}")
                self.append_line("-" * 40)

        self.root.after(0, handle)

    def pretty_status(self, status):
        return {
            "loading": "Loading models",
            "Loading models": "Loading models",
            "listening": "Listening",
            "transcribing": "Transcribing",
            "translating": "Translating",
            "speaking": "Speaking",
            "no_audio": "No audio",
        }.get(status, status)

    def handle_model_progress(self, payload):
        phase = str(payload.get("phase", ""))
        fraction = payload.get("fraction")
        self.phase_var.set(phase)
        if fraction is None:
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress_var.set(max(0, min(100, float(fraction) * 100)))

    def append_line(self, line):
        self.text.insert("end", line + "\n")
        self.text.see("end")

    def download_models(self):
        self.preload_current_models(force_online=True)

    def preload_current_models(self, force_online=False):
        if self.transcriber is not None:
            return
        request = self.current_model_request()
        offline_only = False if force_online else self.offline_only_var.get()
        if offline_only:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            os.environ["OFFLINE_ONLY"] = "1"
        else:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            os.environ["OFFLINE_ONLY"] = "0"
        torch_device = 0 if (torch and torch.cuda.is_available()) else -1
        torch_dtype = torch.float16 if torch_device == 0 else None
        self.status_var.set("Loading models")

        def run_preload():
            try:
                GLOBAL_MODEL_MANAGER.load_models(
                    whisper_model=request["whisper_model"],
                    translation_model=request["translation_model"],
                    torch_device=torch_device,
                    torch_dtype=torch_dtype,
                    offline_only=offline_only,
                    on_event=self.on_event,
                )
                self.root.after(0, lambda: self.status_var.set("Ready"))
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self.append_line(f"Preload skipped: {exc}"))
                self.root.after(0, lambda: self.status_var.set("Ready"))
            finally:
                self.root.after(0, lambda: self.progress.stop())

        threading.Thread(target=run_preload, daemon=True).start()

    def toggle_login(self):
        desired = self.login_var.get()
        ok, message = set_open_at_login(desired)
        actual = is_open_at_login_enabled()
        self.login_var.set(actual)
        if not ok:
            messagebox.showerror("Open at login", message)

    def record_hotkey(self, action):
        self.recording_action = action
        self.status_var.set(f"Recording {HOTKEY_LABELS[action]}")

    def on_key_press(self, event):
        if not self.recording_action:
            return
        combo = format_tk_key_event(event)
        if not combo:
            return
        self.hotkey_vars[self.recording_action].set(combo)
        self.recording_action = None
        self.save_hotkeys_from_ui()
        self.status_var.set("Ready")

    def clear_hotkey(self, action):
        self.hotkey_vars[action].set("")
        self.save_hotkeys_from_ui()

    def reset_hotkeys(self):
        for action, value in DEFAULT_HOTKEYS.items():
            self.hotkey_vars[action].set(value)
        self.save_hotkeys_from_ui()

    def save_hotkeys_from_ui(self):
        hotkeys = {action: variable.get() for action, variable in self.hotkey_vars.items()}
        save_hotkey_config(CONFIG_FILE, hotkeys)
        self.register_hotkeys()

    def register_hotkeys(self):
        hotkeys = {action: variable.get() for action, variable in self.hotkey_vars.items()}
        self.hotkey_manager.register(hotkeys)

    def on_close(self):
        self.hotkey_manager.unregister()
        if self.transcriber is not None:
            self.stop(after=self.root.destroy)
        else:
            self.root.destroy()


def gui_main():
    failure_message = dependency_failure_message()
    if failure_message:
        show_startup_error("Desktop Audio Translator startup error", failure_message)
        return

    require_dependencies()
    hide_console_window()

    root = tk.Tk()
    TranslatorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    gui_main()
