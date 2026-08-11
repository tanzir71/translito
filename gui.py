import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk

from app_config import (
    DEFAULT_HOTKEYS,
    default_transcript_folder,
    load_device_config,
    load_hotkey_config,
    load_language_config,
    load_runtime_config,
    load_speak_config,
    load_transcript_folder,
    save_device_config,
    save_hotkey_config,
    save_language_config,
    save_runtime_config,
    save_speak_config,
    save_transcript_folder,
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
APP_NAME = "Translito"

# Native macOS-inspired palette. Tk's clam theme lets the same colors render
# consistently on Windows 10 and 11 instead of falling back to legacy widgets.
COLORS = {
    "bg": "#1f1f1f",
    "surface": "#252525",
    "surface_2": "#2c2c2e",
    "field": "#303033",
    "border": "#414145",
    "separator": "#343437",
    "text": "#f3f3f5",
    "secondary": "#b1b1b6",
    "tertiary": "#7e7e84",
    "blue": "#0a84ff",
    "blue_hover": "#3298ff",
    "red": "#ff453a",
    "green": "#30d158",
    "orange": "#ff9f0a",
    "purple": "#bf5af2",
    "yellow_bg": "#3a3320",
    "green_bg": "#203629",
    "red_bg": "#3a2424",
}

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
    "toggle": "Toggle Listen / Speak",
    "listen": "Start Listening",
    "speak": "Start Speaking",
    "stop": "Stop",
}

RTL_LANGUAGES = {"ar", "fa", "ur"}


def translation_model_for(source_code, target_code):
    return f"Helsinki-NLP/opus-mt-{source_code}-{target_code}"


def hide_console_window():
    if os.name != "nt":
        return
    if os.environ.get("GUI_HIDE_CONSOLE", "1").strip() == "0":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def show_startup_error(title, message):
    try:
        error_root = tk.Tk()
        error_root.update_idletasks()
        error_root.geometry(
            f"1x1+{error_root.winfo_screenwidth() // 2}+{error_root.winfo_screenheight() // 2}"
        )
        error_root.withdraw()
        messagebox.showerror(title, message, parent=error_root)
        error_root.destroy()
    except Exception:
        print(message)


def app_resource_path(filename):
    """Resolve a bundled PyInstaller resource or a source-tree asset."""
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = bundle_dir / filename
    if bundled.exists():
        return bundled
    return Path(__file__).resolve().parent / "installer" / filename


def center_window(window, parent=None, width=None, height=None):
    """Center a Tk window over its visible parent, or over the current screen."""
    window.update_idletasks()
    width = int(width or window.winfo_width() or window.winfo_reqwidth())
    height = int(height or window.winfo_height() or window.winfo_reqheight())

    parent_is_visible = False
    if parent is not None:
        try:
            parent.update_idletasks()
            parent_is_visible = bool(parent.winfo_exists() and parent.winfo_viewable())
        except tk.TclError:
            parent_is_visible = False

    if parent_is_visible:
        # Top-level geometry coordinates refer to the decorated window frame,
        # while winfo_root* points at the client area below the title bar.
        # Using winfo_x/y keeps the outer Windows frames truly concentric.
        x = parent.winfo_x() + (parent.winfo_width() - width) // 2
        y = parent.winfo_y() + (parent.winfo_height() - height) // 2
    else:
        x = window.winfo_vrootx() + (window.winfo_vrootwidth() - width) // 2
        y = window.winfo_vrooty() + (window.winfo_vrootheight() - height) // 2
        screen_left = window.winfo_vrootx()
        screen_top = window.winfo_vrooty()
        screen_right = screen_left + window.winfo_vrootwidth()
        screen_bottom = screen_top + window.winfo_vrootheight()
        x = max(screen_left, min(x, screen_right - width))
        y = max(screen_top, min(y, screen_bottom - height))
    window.geometry(f"{width}x{height}+{x}+{y}")


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, background=None, **kwargs):
        background = background or COLORS["bg"]
        super().__init__(parent, bg=background, **kwargs)
        self.canvas = tk.Canvas(
            self,
            bg=background,
            highlightthickness=0,
            borderwidth=0,
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self.content = tk.Frame(self.canvas, bg=background)
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.content.bind("<Configure>", self._update_scrollregion)
        self.canvas.bind("<Configure>", self._fit_content_width)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _update_scrollregion(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_content_width(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _bind_wheel(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class MacScale(tk.Canvas):
    """Compact dark slider matching the visual weight of SwiftUI's Slider."""

    def __init__(
        self,
        parent,
        *,
        variable,
        from_,
        to,
        resolution=0,
        command=None,
        background=None,
    ):
        self.variable = variable
        self.minimum = float(from_)
        self.maximum = float(to)
        self.resolution = float(resolution)
        self.command = command
        self._trace_id = None
        super().__init__(
            parent,
            height=24,
            bg=background or COLORS["surface"],
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._set_from_pointer)
        self.bind("<B1-Motion>", self._set_from_pointer)
        self._trace_id = self.variable.trace_add("write", self._variable_changed)

    def _variable_changed(self, *_args):
        try:
            self.after_idle(self._redraw)
        except tk.TclError:
            pass

    def _set_from_pointer(self, event):
        if str(self.cget("state")) == "disabled":
            return
        left, right = 7, max(8, self.winfo_width() - 7)
        fraction = max(0.0, min(1.0, (event.x - left) / max(1, right - left)))
        value = self.minimum + fraction * (self.maximum - self.minimum)
        if self.resolution > 0:
            value = round(value / self.resolution) * self.resolution
        value = max(self.minimum, min(self.maximum, value))
        self.variable.set(value)
        if self.command:
            self.command(str(value))

    def _redraw(self, _event=None):
        if not self.winfo_exists():
            return
        self.delete("scale")
        width = self.winfo_width()
        left, right, center = 7, max(8, width - 7), 12
        span = max(0.000001, self.maximum - self.minimum)
        fraction = max(0.0, min(1.0, (float(self.variable.get()) - self.minimum) / span))
        thumb_x = left + (right - left) * fraction
        disabled = str(self.cget("state")) == "disabled"
        accent = COLORS["tertiary"] if disabled else COLORS["blue"]
        self.create_line(
            left,
            center,
            right,
            center,
            fill=COLORS["field"],
            width=4,
            capstyle="round",
            tags="scale",
        )
        self.create_line(
            left,
            center,
            thumb_x,
            center,
            fill=accent,
            width=4,
            capstyle="round",
            tags="scale",
        )
        self.create_oval(
            thumb_x - 6,
            center - 6,
            thumb_x + 6,
            center + 6,
            fill=accent,
            outline=COLORS["surface_2"],
            width=1,
            tags="scale",
        )

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if hasattr(self, "variable") and ("state" in kwargs or cnf):
            try:
                self.after_idle(self._redraw)
            except tk.TclError:
                pass
        return result

    config = configure


class TranslatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("760x560")
        self.root.minsize(640, 480)
        self.root.configure(bg=COLORS["bg"])
        self.preview_mode = os.environ.get("TRANSLITO_UI_PREVIEW", "0").strip() == "1"

        icon_path = app_resource_path("Translito.ico")
        if icon_path.exists():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass

        self.input_choices = []
        self.listen_choices = []
        self.speak_mic_choices = []
        self.output_choices = []
        self.transcriber = None
        self.last_transcriber = None
        self.last_saved_path = None
        self.transcript_entries = []
        self.transcript_text_labels = []
        self.recording_action = None
        self.settings_window = None
        self.settings_controls = []
        self.tray_icon = None
        self.is_quitting = False
        self.current_status = "Ready"
        self.latest_translation = ""
        self.synthesizer = LocalSpeechSynthesizer()

        language_config = load_language_config(CONFIG_FILE)
        speak_config = load_speak_config(CONFIG_FILE)
        runtime_config = load_runtime_config(CONFIG_FILE)
        hotkeys = load_hotkey_config(CONFIG_FILE)

        env_offline = os.environ.get("OFFLINE_ONLY")
        offline_default = (
            env_offline.strip() == "1" if env_offline is not None else runtime_config.offline_only
        )
        self.mode_var = tk.StringVar(value=runtime_config.last_mode)
        self.listen_device_var = tk.StringVar(value="")
        self.speak_mic_var = tk.StringVar(value=speak_config.mic_name)
        self.speak_output_var = tk.StringVar(value=speak_config.output_device_name)
        self.listen_source_var = tk.StringVar(value=self.language_name_for_iso(language_config.source))
        self.listen_target_var = tk.StringVar(value=self.language_name_for_iso(language_config.target))
        self.speak_source_var = tk.StringVar(value=self.language_name_for_iso(speak_config.source))
        self.speak_target_var = tk.StringVar(value=self.language_name_for_iso(speak_config.target))
        self.whisper_var = tk.StringVar(value=language_config.whisper_model)
        self.offline_only_var = tk.BooleanVar(value=offline_default)
        self.monitor_var = tk.BooleanVar(value=speak_config.monitor_spoken_audio)
        self.voice_var = tk.StringVar(value=speak_config.voice or "Automatic")
        self.noise_gate_var = tk.DoubleVar(value=runtime_config.mic_noise_gate)
        self.chunk_duration_var = tk.DoubleVar(value=runtime_config.chunk_duration)
        self.transcript_folder_var = tk.StringVar(value=str(load_transcript_folder(CONFIG_FILE)))
        self.status_var = tk.StringVar(value="Ready")
        self.phase_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)
        self.routing_var = tk.StringVar(value="")
        self.hint_var = tk.StringVar(value="")
        self.error_var = tk.StringVar(value="")
        self.entry_count_var = tk.StringVar(value="0 entries")
        self.peak_var = tk.StringVar(value="peak 0.0000")
        self.login_var = tk.BooleanVar(value=is_open_at_login_enabled())
        self.hotkey_vars = {
            action: tk.StringVar(value=hotkeys.get(action, default))
            for action, default in DEFAULT_HOTKEYS.items()
        }

        self.apply_styles()
        self.build_ui()
        self.bind_events()

        self.hotkey_manager = GlobalHotkeyManager(
            callbacks={
                "toggle": lambda: self.root.after(0, self.hotkey_toggle),
                "listen": lambda: self.root.after(0, lambda: self.hotkey_start_mode("listen")),
                "speak": lambda: self.root.after(0, lambda: self.hotkey_start_mode("speak")),
                "stop": lambda: self.root.after(0, self.stop),
            },
            on_error=lambda message: self.root.after(0, lambda: self.show_error(message)),
        )
        if not self.preview_mode:
            self.register_hotkeys()
            self.setup_tray()

        self.refresh_devices(show_error=not self.preview_mode)
        self.set_mode(self.mode_var.get(), force=True)
        self.refresh_voices()
        self.update_noise_gate_label()
        self.update_chunk_label()
        self.update_transcript_state()
        if not self.preview_mode:
            self.root.after(350, self.preload_current_models)
            self.root.after(3000, self.auto_refresh_devices)

    # ------------------------------------------------------------------
    # Window construction

    def apply_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.style = style
        self.root.option_add("*Font", "{Segoe UI} 10")
        self.root.option_add("*TCombobox*Listbox.background", COLORS["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLORS["blue"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")

        style.configure("Dark.TFrame", background=COLORS["bg"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure("Dark.TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure(
            "Secondary.TLabel", background=COLORS["bg"], foreground=COLORS["secondary"]
        )
        style.configure(
            "Surface.TLabel", background=COLORS["surface"], foreground=COLORS["text"]
        )
        style.configure(
            "SurfaceSecondary.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["secondary"],
        )
        style.configure(
            "Mac.TButton",
            background=COLORS["surface_2"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["surface_2"],
            darkcolor=COLORS["surface_2"],
            padding=(12, 6),
            relief="flat",
        )
        style.map(
            "Mac.TButton",
            background=[("active", COLORS["field"]), ("disabled", COLORS["surface"])],
            foreground=[("disabled", COLORS["tertiary"])],
        )
        style.configure(
            "Icon.TButton",
            background=COLORS["surface_2"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["surface_2"],
            darkcolor=COLORS["surface_2"],
            padding=(6, 5),
            relief="flat",
            font=("Segoe UI Symbol", 10),
        )
        style.map(
            "Icon.TButton",
            background=[("active", COLORS["field"]), ("disabled", COLORS["surface"])],
            foreground=[("disabled", COLORS["tertiary"])],
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["blue"],
            foreground="white",
            bordercolor=COLORS["blue"],
            lightcolor=COLORS["blue"],
            darkcolor=COLORS["blue"],
            padding=(12, 5),
            relief="flat",
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["blue_hover"]), ("disabled", COLORS["field"])],
            foreground=[("disabled", COLORS["tertiary"])],
        )
        style.configure(
            "Stop.TButton",
            background=COLORS["red"],
            foreground="white",
            bordercolor=COLORS["red"],
            lightcolor=COLORS["red"],
            darkcolor=COLORS["red"],
            padding=(12, 5),
            relief="flat",
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "SegmentActive.TButton",
            background=COLORS["field"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            padding=(14, 6),
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "SegmentInactive.TButton",
            background=COLORS["surface"],
            foreground=COLORS["secondary"],
            bordercolor=COLORS["border"],
            padding=(14, 6),
            relief="flat",
            font=("Segoe UI", 9),
        )
        style.map(
            "SegmentInactive.TButton",
            background=[("active", COLORS["surface_2"])],
            foreground=[("active", COLORS["text"]), ("disabled", COLORS["tertiary"])],
        )
        style.configure(
            "Dark.TCombobox",
            fieldbackground=COLORS["field"],
            background=COLORS["field"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["secondary"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            padding=6,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", COLORS["field"]), ("disabled", COLORS["surface"])],
            foreground=[("readonly", COLORS["text"]), ("disabled", COLORS["tertiary"])],
            selectbackground=[("readonly", COLORS["field"])],
            selectforeground=[("readonly", COLORS["text"])],
        )
        style.configure(
            "Dark.Horizontal.TProgressbar",
            troughcolor=COLORS["field"],
            background=COLORS["blue"],
            bordercolor=COLORS["field"],
            lightcolor=COLORS["blue"],
            darkcolor=COLORS["blue"],
        )
        style.configure(
            "Dark.Vertical.TScrollbar",
            background=COLORS["field"],
            troughcolor=COLORS["bg"],
            bordercolor=COLORS["bg"],
            arrowcolor=COLORS["secondary"],
            lightcolor=COLORS["field"],
            darkcolor=COLORS["field"],
            borderwidth=0,
            arrowsize=10,
        )

    def build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(8, weight=1)

        self.mode_bar = tk.Frame(self.root, bg=COLORS["bg"], height=48)
        self.mode_bar.grid(row=0, column=0, sticky="ew")
        self.mode_bar.columnconfigure(0, weight=1)
        segment = tk.Frame(
            self.mode_bar,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        segment.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))
        self.listen_mode_button = ttk.Button(
            segment,
            text="Translate Audio",
            style="SegmentActive.TButton",
            command=lambda: self.set_mode("listen"),
        )
        self.listen_mode_button.pack(side="left")
        self.speak_mode_button = ttk.Button(
            segment,
            text="Speak Translation",
            style="SegmentInactive.TButton",
            command=lambda: self.set_mode("speak"),
        )
        self.speak_mode_button.pack(side="left")
        self.settings_button = ttk.Button(
            self.mode_bar,
            text="⚙",
            width=2,
            style="Icon.TButton",
            command=self.open_settings,
        )
        self.settings_button.grid(row=0, column=1, sticky="e", padx=12, pady=(10, 4))

        self._separator(1)

        self.controls_host = tk.Frame(self.root, bg=COLORS["bg"])
        self.controls_host.grid(row=2, column=0, sticky="ew")
        self.controls_host.columnconfigure(0, weight=1)
        self.listen_frame = self._build_listen_controls(self.controls_host)
        self.speak_frame = self._build_speak_controls(self.controls_host)

        self.routing_banner = tk.Frame(self.root, bg=COLORS["yellow_bg"])
        self.routing_icon = tk.Label(
            self.routing_banner,
            text="!",
            bg=COLORS["yellow_bg"],
            fg=COLORS["orange"],
            padx=12,
            pady=10,
            font=("Segoe UI Semibold", 10),
        )
        self.routing_icon.pack(side="left", anchor="n")
        self.routing_label = tk.Label(
            self.routing_banner,
            textvariable=self.routing_var,
            bg=COLORS["yellow_bg"],
            fg=COLORS["secondary"],
            justify="left",
            anchor="w",
            wraplength=820,
            padx=0,
            pady=10,
            font=("Segoe UI", 9),
        )
        self.routing_label.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self._separator(4)
        self._build_status_bar()
        self._build_banners()
        self._separator(7)
        self._build_transcript_area()
        self._separator(9)
        self._build_bottom_bar()

    def _separator(self, row):
        tk.Frame(self.root, bg=COLORS["separator"], height=1).grid(
            row=row, column=0, sticky="ew"
        )

    def _field(self, parent, label, variable, width=18):
        frame = tk.Frame(parent, bg=COLORS["bg"])
        tk.Label(
            frame,
            text=label,
            bg=COLORS["bg"],
            fg=COLORS["secondary"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill="x", pady=(0, 3))
        combo = ttk.Combobox(
            frame,
            textvariable=variable,
            state="readonly",
            width=width,
            style="Dark.TCombobox",
        )
        combo.pack(fill="x")
        return frame, combo

    def _build_listen_controls(self, parent):
        frame = tk.Frame(parent, bg=COLORS["bg"], padx=12, pady=10)
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(0, weight=3)
        frame.columnconfigure(2, weight=2)
        frame.columnconfigure(3, weight=2)

        source_field, self.listen_combo = self._field(
            frame, "Source", self.listen_device_var, width=26
        )
        source_field.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.btn_refresh_listen = ttk.Button(
            frame, text="↻", width=2, style="Icon.TButton", command=self.refresh_devices
        )
        self.btn_refresh_listen.grid(row=0, column=1, sticky="s", padx=(0, 10))

        from_field, self.listen_source_combo = self._field(
            frame, "From", self.listen_source_var, width=12
        )
        self.listen_source_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        from_field.grid(row=0, column=2, sticky="ew", padx=(0, 10))

        to_field, self.listen_target_combo = self._field(
            frame, "To", self.listen_target_var, width=12
        )
        self.listen_target_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        to_field.grid(row=0, column=3, sticky="ew", padx=(0, 12))

        self.listen_action_button = ttk.Button(
            frame,
            text="▶  Start",
            width=9,
            style="Primary.TButton",
            command=self.toggle_capture,
        )
        self.listen_action_button.grid(row=0, column=4, sticky="s")
        return frame

    def _build_speak_controls(self, parent):
        frame = tk.Frame(parent, bg=COLORS["bg"], padx=12, pady=10)
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=2)
        frame.columnconfigure(3, weight=1)
        frame.columnconfigure(4, weight=1)

        mic_field, self.speak_mic_combo = self._field(
            frame, "Microphone", self.speak_mic_var, width=13
        )
        mic_field.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        output_field, self.speak_output_combo = self._field(
            frame, "Speak to", self.speak_output_var, width=13
        )
        output_field.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        self.btn_refresh_speak = ttk.Button(
            frame, text="↻", width=2, style="Icon.TButton", command=self.refresh_devices
        )
        self.btn_refresh_speak.grid(row=0, column=2, sticky="s", padx=(0, 10))

        from_field, self.speak_source_combo = self._field(
            frame, "From", self.speak_source_var, width=8
        )
        self.speak_source_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        from_field.grid(row=0, column=3, sticky="ew", padx=(0, 10))

        to_field, self.speak_target_combo = self._field(
            frame, "To", self.speak_target_var, width=8
        )
        self.speak_target_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        to_field.grid(row=0, column=4, sticky="ew", padx=(0, 12))

        self.speak_action_button = ttk.Button(
            frame,
            text="●  Start",
            width=9,
            style="Primary.TButton",
            command=self.toggle_capture,
        )
        self.speak_action_button.grid(row=0, column=5, sticky="s")
        return frame

    def _build_status_bar(self):
        self.status_bar = tk.Frame(self.root, bg=COLORS["bg"], padx=12, pady=8)
        self.status_bar.grid(row=5, column=0, sticky="ew")
        self.status_bar.columnconfigure(4, weight=1)

        self.status_dot = tk.Canvas(
            self.status_bar,
            width=14,
            height=14,
            bg=COLORS["bg"],
            highlightthickness=0,
        )
        self.status_dot.create_oval(2, 2, 12, 12, fill=COLORS["tertiary"], outline="", tags="dot")
        self.status_dot.grid(row=0, column=0, padx=(0, 8))
        tk.Label(
            self.status_bar,
            textvariable=self.status_var,
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 9),
        ).grid(row=0, column=1, sticky="w")

        self.progress = ttk.Progressbar(
            self.status_bar,
            variable=self.progress_var,
            maximum=100,
            length=125,
            style="Dark.Horizontal.TProgressbar",
        )
        self.phase_label = tk.Label(
            self.status_bar,
            textvariable=self.phase_var,
            bg=COLORS["bg"],
            fg=COLORS["secondary"],
            font=("Segoe UI", 8),
            anchor="w",
        )

        self.level_frame = tk.Frame(self.status_bar, bg=COLORS["bg"])
        tk.Label(
            self.level_frame,
            text="⌁",
            bg=COLORS["bg"],
            fg=COLORS["secondary"],
            font=("Segoe UI", 11),
        ).pack(side="left", padx=(0, 5))
        self.level_canvas = tk.Canvas(
            self.level_frame,
            width=110,
            height=8,
            bg=COLORS["field"],
            highlightthickness=0,
        )
        self.level_canvas.create_rectangle(0, 0, 0, 8, fill=COLORS["green"], outline="", tags="level")
        self.level_canvas.pack(side="left")
        tk.Label(
            self.level_frame,
            textvariable=self.peak_var,
            bg=COLORS["bg"],
            fg=COLORS["tertiary"],
            font=("Cascadia Mono", 8),
        ).pack(side="left", padx=(6, 0))
        self.level_frame.grid(row=0, column=5, sticky="e")
        self.level_frame.grid_remove()

    def _build_banners(self):
        self.banner_host = tk.Frame(self.root, bg=COLORS["bg"])
        self.banner_host.grid(row=6, column=0, sticky="ew")
        self.hint_frame = tk.Frame(self.banner_host, bg=COLORS["yellow_bg"])
        self.hint_icon = tk.Label(
            self.hint_frame,
            text="●",
            bg=COLORS["yellow_bg"],
            fg=COLORS["orange"],
            padx=12,
        )
        self.hint_icon.pack(side="left")
        self.hint_label = tk.Label(
            self.hint_frame,
            textvariable=self.hint_var,
            bg=COLORS["yellow_bg"],
            fg=COLORS["secondary"],
            justify="left",
            anchor="w",
            wraplength=800,
            pady=8,
        )
        self.hint_label.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self.error_frame = tk.Frame(self.banner_host, bg=COLORS["red_bg"])
        self.error_icon = tk.Label(
            self.error_frame,
            text="!",
            bg=COLORS["red_bg"],
            fg=COLORS["red"],
            font=("Segoe UI Semibold", 10),
            padx=12,
        )
        self.error_icon.pack(side="left")
        self.error_label = tk.Label(
            self.error_frame,
            textvariable=self.error_var,
            bg=COLORS["red_bg"],
            fg="#ffb4ae",
            justify="left",
            anchor="w",
            wraplength=800,
            pady=8,
        )
        self.error_label.pack(side="left", fill="x", expand=True, padx=(0, 12))

    def _build_transcript_area(self):
        self.transcript_host = tk.Frame(self.root, bg=COLORS["bg"])
        self.transcript_host.grid(row=8, column=0, sticky="nsew")
        self.transcript_host.rowconfigure(0, weight=1)
        self.transcript_host.columnconfigure(0, weight=1)

        self.transcript_scroll = ScrollableFrame(self.transcript_host, background=COLORS["bg"])
        self.transcript_scroll.grid(row=0, column=0, sticky="nsew")

        self.empty_state = tk.Frame(self.transcript_host, bg=COLORS["bg"])
        empty_icon = tk.Canvas(
            self.empty_state,
            width=40,
            height=36,
            bg=COLORS["bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        empty_icon.create_line(
            6, 5, 34, 5, 34, 25, 18, 25, 11, 31, 11, 25, 6, 25, 6, 5,
            fill=COLORS["tertiary"],
            width=2,
            joinstyle="round",
        )
        empty_icon.create_line(12, 12, 28, 12, fill=COLORS["tertiary"], width=2)
        empty_icon.create_line(12, 18, 24, 18, fill=COLORS["tertiary"], width=2)
        empty_icon.pack(pady=(0, 8))
        self.empty_title_label = tk.Label(
            self.empty_state,
            text="Transcripts will appear here",
            bg=COLORS["bg"],
            fg=COLORS["secondary"],
            font=("Segoe UI Semibold", 11),
        )
        self.empty_title_label.pack()
        self.empty_help_label = tk.Label(
            self.empty_state,
            text=(
                "Choose a source and press Start. Loopback devices capture whatever "
                "Windows is playing; microphones capture live speech."
            ),
            bg=COLORS["bg"],
            fg=COLORS["tertiary"],
            justify="center",
            wraplength=460,
            font=("Segoe UI", 9),
        )
        self.empty_help_label.pack(pady=(5, 0))

    def _build_bottom_bar(self):
        bar = tk.Frame(self.root, bg=COLORS["bg"], padx=12, pady=12)
        bar.grid(row=10, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        tk.Label(
            bar,
            textvariable=self.entry_count_var,
            bg=COLORS["bg"],
            fg=COLORS["secondary"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w")
        self.clear_button = ttk.Button(
            bar, text="Clear", style="Mac.TButton", command=self.clear_transcript
        )
        self.clear_button.grid(row=0, column=2, padx=(8, 0))
        self.save_button = ttk.Button(
            bar, text="Save Transcript", style="Mac.TButton", command=self.save_transcript
        )
        self.save_button.grid(row=0, column=3, padx=(8, 0))
        self.show_folder_button = ttk.Button(
            bar, text="Show in Explorer", style="Mac.TButton", command=self.reveal_transcripts
        )
        self.show_folder_button.grid(row=0, column=4, padx=(8, 0))

    # ------------------------------------------------------------------
    # Settings window

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            center_window(self.settings_window, self.root, 520, 560)
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("Translito Settings")
        window.geometry("520x560")
        window.minsize(520, 460)
        window.resizable(False, True)
        window.configure(bg=COLORS["bg"])
        window.transient(self.root)
        try:
            window.iconbitmap(default=str(app_resource_path("Translito.ico")))
        except tk.TclError:
            pass
        scroll = ScrollableFrame(window, background=COLORS["bg"])
        scroll.pack(fill="both", expand=True)
        content = scroll.content
        content.configure(padx=18, pady=14)
        self.settings_controls = []

        general = self._settings_section(content, "General")
        login = tk.Checkbutton(
            general,
            text="Open at login",
            variable=self.login_var,
            command=self.toggle_login,
            **self._checkbutton_options(),
        )
        login.pack(anchor="w")
        self.settings_controls.append(login)

        hotkeys = self._settings_section(content, "Hotkeys")
        for action in ("toggle", "listen", "speak", "stop"):
            row = tk.Frame(hotkeys, bg=COLORS["surface"])
            row.pack(fill="x", pady=3)
            row.columnconfigure(1, weight=1)
            tk.Label(
                row,
                text=HOTKEY_LABELS[action],
                bg=COLORS["surface"],
                fg=COLORS["text"],
                width=19,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            entry = tk.Entry(
                row,
                textvariable=self.hotkey_vars[action],
                bg=COLORS["field"],
                fg=COLORS["text"],
                insertbackground=COLORS["text"],
                relief="flat",
                highlightthickness=1,
                highlightbackground=COLORS["border"],
                highlightcolor=COLORS["blue"],
            )
            entry.grid(row=0, column=1, sticky="ew", padx=(8, 8), ipady=6)
            record = ttk.Button(
                row,
                text="Record",
                style="Mac.TButton",
                command=lambda a=action: self.record_hotkey(a),
            )
            record.grid(row=0, column=2, padx=(0, 6))
            clear = ttk.Button(
                row,
                text="Clear",
                style="Mac.TButton",
                command=lambda a=action: self.clear_hotkey(a),
            )
            clear.grid(row=0, column=3)
            self.settings_controls.extend((entry, record, clear))
        ttk.Button(
            hotkeys, text="Reset Defaults", style="Mac.TButton", command=self.reset_hotkeys
        ).pack(anchor="e", pady=(7, 0))
        self._settings_help(
            hotkeys,
            "Hotkeys work system-wide. Toggle starts the last-used mode or switches between listening and speaking.",
        )

        languages = self._settings_section(content, "Languages")
        listen_source_settings = self._settings_combo(
            languages,
            "Source language",
            self.listen_source_var,
            [name for name, _bcp, _iso in LANGUAGES],
        )
        listen_target_settings = self._settings_combo(
            languages,
            "Target language",
            self.listen_target_var,
            [name for name, _bcp, _iso in LANGUAGES],
        )
        for combo in (listen_source_settings, listen_target_settings):
            combo.bind("<<ComboboxSelected>>", lambda _event: self.persist_settings())

        recognition = self._settings_section(content, "Speech Recognition")
        whisper_settings = self._settings_combo(
            recognition, "Whisper model", self.whisper_var, WHISPER_MODELS
        )
        whisper_settings.bind("<<ComboboxSelected>>", lambda _event: self.persist_settings())
        slider_row = tk.Frame(recognition, bg=COLORS["surface"])
        slider_row.pack(fill="x", pady=5)
        tk.Label(
            slider_row,
            text="Chunk length",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            width=19,
            anchor="w",
        ).pack(side="left")
        chunk_scale = MacScale(
            slider_row,
            variable=self.chunk_duration_var,
            from_=3,
            to=15,
            resolution=1,
            command=self.update_chunk_duration,
            background=COLORS["surface"],
        )
        chunk_scale.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.chunk_label = tk.Label(
            slider_row,
            text="6 s",
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            width=5,
            anchor="w",
            font=("Cascadia Mono", 9),
        )
        self.chunk_label.pack(side="left")
        offline = tk.Checkbutton(
            recognition,
            text="Offline mode (use already-downloaded models only)",
            variable=self.offline_only_var,
            command=self.persist_settings,
            **self._checkbutton_options(),
        )
        offline.pack(anchor="w", pady=(6, 2))
        ttk.Button(
            recognition,
            text="Download Models",
            style="Mac.TButton",
            command=self.download_models,
        ).pack(anchor="w", pady=(5, 0))
        self._settings_help(
            recognition,
            "Models download once, then run locally. Smaller Whisper models start faster; larger models are more accurate.",
        )
        self.settings_controls.extend((whisper_settings, chunk_scale, offline))

        capture = self._settings_section(content, "Capture")
        gate_row = tk.Frame(capture, bg=COLORS["surface"])
        gate_row.pack(fill="x", pady=5)
        tk.Label(
            gate_row,
            text="Mic noise gate",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            width=19,
            anchor="w",
        ).pack(side="left")
        gate_scale = MacScale(
            gate_row,
            variable=self.noise_gate_var,
            from_=0,
            to=0.008,
            resolution=0.0001,
            command=lambda _value: (self.update_noise_gate_label(), self.persist_settings()),
            background=COLORS["surface"],
        )
        gate_scale.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.noise_gate_label = tk.Label(
            gate_row,
            text="Medium",
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            width=10,
            anchor="w",
            font=("Cascadia Mono", 9),
        )
        self.noise_gate_label.pack(side="left")
        self._settings_help(
            capture,
            "Raise this in noisy rooms; lower it if quiet speech is clipped. It applies only to real microphones, never loopback or virtual sources.",
        )
        self.settings_controls.append(gate_scale)

        speak = self._settings_section(content, "Speak Mode")
        voice_settings = self._settings_combo(speak, "Voice", self.voice_var, ["Automatic"])
        self.voice_settings_combo = voice_settings
        monitor = tk.Checkbutton(
            speak,
            text="Also play spoken translation through my speakers",
            variable=self.monitor_var,
            command=self.persist_settings,
            **self._checkbutton_options(),
        )
        monitor.pack(anchor="w", pady=(7, 2))
        self._settings_help(
            speak,
            "Route Speak Mode into Slack, Zoom, Teams, or Meet with VB-Audio Virtual Cable. Use headphones to prevent feedback.",
        )
        self.settings_controls.extend((voice_settings, monitor))
        self.refresh_voices()

        transcripts = self._settings_section(content, "Transcripts")
        folder_label = tk.Label(
            transcripts,
            textvariable=self.transcript_folder_var,
            bg=COLORS["field"],
            fg=COLORS["secondary"],
            anchor="w",
            justify="left",
            padx=8,
            pady=7,
            wraplength=440,
        )
        folder_label.pack(fill="x", pady=(0, 8))
        folder_buttons = tk.Frame(transcripts, bg=COLORS["surface"])
        folder_buttons.pack(fill="x")
        ttk.Button(
            folder_buttons, text="Choose Folder…", style="Mac.TButton", command=self.choose_folder
        ).pack(side="left")
        ttk.Button(
            folder_buttons, text="Use Default", style="Mac.TButton", command=self.reset_folder
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            folder_buttons, text="Open Folder", style="Mac.TButton", command=self.open_folder
        ).pack(side="left", padx=(8, 0))

        if self.transcriber is not None:
            self._settings_help(content, "Stop capture to change settings.", color=COLORS["orange"])
            self._set_settings_controls_state(False)
        self.update_noise_gate_label()
        self.update_chunk_label()
        center_window(window, self.root, 520, 560)
        window.lift()
        window.focus_force()

    def _settings_section(self, parent, title):
        outer = tk.Frame(parent, bg=COLORS["bg"])
        outer.pack(fill="x", pady=(0, 14))
        tk.Label(
            outer,
            text=title,
            bg=COLORS["bg"],
            fg=COLORS["secondary"],
            font=("Segoe UI Semibold", 9),
            anchor="w",
        ).pack(fill="x", padx=3, pady=(0, 5))
        card = tk.Frame(
            outer,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            padx=12,
            pady=11,
        )
        card.pack(fill="x")
        return card

    def _settings_combo(self, parent, label, variable, values):
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", pady=4)
        tk.Label(
            row,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            width=19,
            anchor="w",
        ).pack(side="left")
        combo = ttk.Combobox(
            row,
            textvariable=variable,
            values=values,
            state="readonly",
            style="Dark.TCombobox",
        )
        combo.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.settings_controls.append(combo)
        return combo

    def _settings_help(self, parent, text, color=None):
        tk.Label(
            parent,
            text=text,
            bg=parent.cget("bg"),
            fg=color or COLORS["tertiary"],
            justify="left",
            anchor="w",
            wraplength=440,
            font=("Segoe UI", 8),
        ).pack(fill="x", pady=(8, 0))

    def _checkbutton_options(self):
        return {
            "bg": COLORS["surface"],
            "fg": COLORS["text"],
            "activebackground": COLORS["surface"],
            "activeforeground": COLORS["text"],
            "selectcolor": COLORS["field"],
            "highlightthickness": 0,
        }

    # ------------------------------------------------------------------
    # Devices and settings

    def bind_events(self):
        self.listen_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self.persist_current_listen_device()
        )
        self.speak_mic_combo.bind("<<ComboboxSelected>>", lambda _event: self.persist_settings())
        self.speak_output_combo.bind(
            "<<ComboboxSelected>>", lambda _event: (self.update_routing_banner(), self.persist_settings())
        )
        self.listen_source_combo.bind("<<ComboboxSelected>>", lambda _event: self.persist_settings())
        self.listen_target_combo.bind("<<ComboboxSelected>>", lambda _event: self.persist_settings())
        self.speak_source_combo.bind("<<ComboboxSelected>>", lambda _event: self.persist_settings())
        self.speak_target_combo.bind(
            "<<ComboboxSelected>>", lambda _event: (self.refresh_voices(), self.persist_settings())
        )
        self.root.bind_all("<KeyPress>", self.on_key_press)
        self.root.bind("<Configure>", self.on_root_configure, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_root_configure(self, event):
        if event.widget is not self.root:
            return
        content_wrap = max(320, event.width - 56)
        self.routing_label.configure(wraplength=content_wrap)
        self.hint_label.configure(wraplength=content_wrap)
        self.error_label.configure(wraplength=content_wrap)
        self.empty_help_label.configure(wraplength=min(460, max(300, event.width - 80)))
        transcript_wrap = max(280, event.width - 56)
        for label in tuple(self.transcript_text_labels):
            try:
                label.configure(wraplength=transcript_wrap)
            except tk.TclError:
                self.transcript_text_labels.remove(label)

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
                self.show_error(f"Unable to list audio devices: {exc}")
            return

        self.listen_choices = self.input_choices
        self.speak_mic_choices = [
            choice for choice in self.input_choices if not choice.is_loopback and not choice.is_virtual
        ]
        if not self.speak_mic_choices:
            self.speak_mic_choices = [
                choice for choice in self.input_choices if not choice.is_loopback
            ]
        if not self.speak_mic_choices:
            self.speak_mic_choices = self.input_choices

        self.listen_combo["values"] = [choice.display_name for choice in self.listen_choices]
        self.speak_mic_combo["values"] = [choice.display_name for choice in self.speak_mic_choices]
        self.speak_output_combo["values"] = [choice.display_name for choice in self.output_choices]
        self.select_combo_by_name(self.listen_combo, self.listen_choices, listen_name)
        self.select_combo_by_name(
            self.speak_mic_combo,
            self.speak_mic_choices,
            mic_name,
            first_real_microphone(self.speak_mic_choices),
        )
        self.select_combo_by_name(
            self.speak_output_combo,
            self.output_choices,
            output_name,
            first_virtual_output(self.output_choices),
        )
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

    def set_mode(self, mode, force=False):
        if self.transcriber is not None and not force:
            return
        mode = mode if mode in {"listen", "speak"} else "listen"
        self.mode_var.set(mode)
        self.listen_mode_button.configure(
            style="SegmentActive.TButton" if mode == "listen" else "SegmentInactive.TButton"
        )
        self.speak_mode_button.configure(
            style="SegmentActive.TButton" if mode == "speak" else "SegmentInactive.TButton"
        )
        if mode == "speak":
            self.listen_frame.grid_remove()
            self.speak_frame.grid(row=0, column=0, sticky="ew")
            self.routing_banner.grid(row=3, column=0, sticky="ew")
        else:
            self.speak_frame.grid_remove()
            self.listen_frame.grid(row=0, column=0, sticky="ew")
            self.routing_banner.grid_remove()
        self.persist_settings()

    def update_routing_banner(self):
        output = self.selected_output_choice()
        output_name = output.name if output else ""
        self.routing_var.set(conference_mic_hint(output_name))
        is_virtual = bool(output and output.is_virtual)
        background = COLORS["green_bg"] if is_virtual else COLORS["yellow_bg"]
        self.routing_banner.configure(bg=background)
        self.routing_label.configure(bg=background)
        self.routing_icon.configure(
            text="✓" if is_virtual else "!",
            bg=background,
            fg=COLORS["green"] if is_virtual else COLORS["orange"],
        )

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
        if hasattr(self, "noise_gate_label"):
            self.noise_gate_label.configure(text=label)

    def update_chunk_label(self):
        if hasattr(self, "chunk_label"):
            self.chunk_label.configure(text=f"{int(round(self.chunk_duration_var.get()))} s")

    def update_chunk_duration(self, value):
        rounded = float(round(float(value)))
        if self.chunk_duration_var.get() != rounded:
            self.chunk_duration_var.set(rounded)
        self.update_chunk_label()
        self.persist_settings()

    def refresh_voices(self):
        _name, _bcp47, target_iso = self.language_entry_by_name(self.speak_target_var.get())
        def load():
            voices = self.synthesizer.available_voices(target_iso)
            try:
                self.root.after(0, lambda: self._apply_voices(voices))
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=load, daemon=True).start()

    def _apply_voices(self, voices):
        if hasattr(self, "voice_settings_combo") and self.voice_settings_combo.winfo_exists():
            self.voice_settings_combo["values"] = voices
        if self.voice_var.get() not in voices:
            self.voice_var.set("Automatic")

    def persist_current_listen_device(self):
        if self.preview_mode:
            return
        choice = self.selected_listen_choice()
        if choice:
            save_device_config(choice.name, CONFIG_FILE)

    def persist_settings(self):
        if self.preview_mode:
            return
        _listen_name, _listen_bcp, listen_source = self.language_entry_by_name(
            self.listen_source_var.get()
        )
        _target_name, _target_bcp, listen_target = self.language_entry_by_name(
            self.listen_target_var.get()
        )
        _speak_name, _speak_bcp, speak_source = self.language_entry_by_name(
            self.speak_source_var.get()
        )
        _speak_target_name, _speak_target_bcp, speak_target = self.language_entry_by_name(
            self.speak_target_var.get()
        )
        save_language_config(listen_source, listen_target, self.whisper_var.get(), CONFIG_FILE)
        mic_choice = self.selected_speak_mic_choice()
        output_choice = self.selected_output_choice()
        save_speak_config(
            CONFIG_FILE,
            source=speak_source,
            target=speak_target,
            mic_name=mic_choice.name if mic_choice else self.speak_mic_var.get(),
            output_device_name=output_choice.name if output_choice else self.speak_output_var.get(),
            voice=self.voice_var.get(),
            monitor_spoken_audio=self.monitor_var.get(),
        )
        save_runtime_config(
            CONFIG_FILE,
            mic_noise_gate=self.noise_gate_var.get(),
            last_mode=self.mode_var.get(),
            chunk_duration=self.chunk_duration_var.get(),
            offline_only=self.offline_only_var.get(),
        )

    def choose_folder(self):
        selected = filedialog.askdirectory(
            parent=self.settings_window or self.root,
            title="Choose Transcript Folder",
            initialdir=self.transcript_folder_var.get(),
        )
        if selected:
            self.transcript_folder_var.set(selected)
            save_transcript_folder(selected, CONFIG_FILE)

    def reset_folder(self):
        folder = default_transcript_folder()
        self.transcript_folder_var.set(str(folder))
        save_transcript_folder(folder, CONFIG_FILE)

    def open_folder(self):
        folder = Path(self.transcript_folder_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)

    # ------------------------------------------------------------------
    # Runtime actions

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
            _src_name, src_bcp47, src_iso = self.language_entry_by_name(
                self.speak_source_var.get()
            )
            _tgt_name, _tgt_bcp47, tgt_iso = self.language_entry_by_name(
                self.speak_target_var.get()
            )
        else:
            _src_name, src_bcp47, src_iso = self.language_entry_by_name(
                self.listen_source_var.get()
            )
            _tgt_name, _tgt_bcp47, tgt_iso = self.language_entry_by_name(
                self.listen_target_var.get()
            )
        return {
            "mode": mode,
            "src_bcp47": src_bcp47,
            "src_iso": src_iso,
            "tgt_iso": tgt_iso,
            "whisper_model": self.whisper_var.get().strip() or "openai/whisper-small",
            "translation_model": translation_model_for(src_iso, tgt_iso),
        }

    def toggle_capture(self):
        if self.transcriber is None:
            self.start()
        else:
            self.stop()

    def start(self):
        if self.transcriber is not None:
            return
        request = self.current_model_request()
        if request["src_iso"] == request["tgt_iso"]:
            messagebox.showwarning(
                "Language",
                "Source and target languages must be different.",
                parent=self.root,
            )
            return

        self.configure_offline_env()
        self.persist_settings()
        self.hide_banners()
        mic_noise_gate = float(self.noise_gate_var.get())

        if request["mode"] == "speak":
            mic_choice = self.selected_speak_mic_choice()
            output_choice = self.selected_output_choice()
            if mic_choice is None:
                messagebox.showwarning(
                    "Microphone", "Select a microphone first.", parent=self.root
                )
                return
            if output_choice and not output_choice.is_virtual and same_physical_device(
                mic_choice.name, output_choice.name
            ):
                messagebox.showwarning(
                    "Routing",
                    "Choose a different output device for Speak Mode.",
                    parent=self.root,
                )
                return
            selected_device = mic_choice.raw
            output_name = output_choice.name if output_choice else ""
        else:
            listen_choice = self.selected_listen_choice()
            if listen_choice is None:
                messagebox.showwarning(
                    "Device", "Select an audio device first.", parent=self.root
                )
                return
            selected_device = listen_choice.raw
            output_name = ""
            save_device_config(listen_choice.name, CONFIG_FILE)

        self.lock_controls(True)
        self.set_status("Loading models")
        self.update_action_button(running=False, loading=True)

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
                    chunk_duration=self.chunk_duration_var.get(),
                    transcript_folder=self.transcript_folder_var.get(),
                )
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self.start_failed(exc))
                return

            def finish_start():
                self.transcriber = transcriber
                self.set_status("Listening")
                self.phase_var.set("")
                self.progress.stop()
                self.progress.grid_remove()
                self.phase_label.grid_remove()
                self.level_frame.grid()
                self.update_action_button(running=True)
                transcriber.start_background(enable_keyboard_shortcuts=False)

            self.root.after(0, finish_start)

        threading.Thread(target=run_start, daemon=True).start()

    def start_failed(self, exc):
        self.lock_controls(False)
        self.set_status("Error")
        self.update_action_button(running=False)
        self.show_error(str(exc))

    def stop(self, after=None):
        transcriber = self.transcriber
        if transcriber is None:
            if callable(after):
                after()
            return
        self.set_status("Stopping")
        self.update_action_button(running=True, loading=True)
        transcriber.stop_background()

        def finalize():
            transcriber.join_background()
            saved_path = transcriber.save_transcript()

            def done():
                self.last_transcriber = transcriber
                self.last_saved_path = saved_path or transcriber.last_saved_path
                self.transcriber = None
                self.lock_controls(False)
                self.set_status("Ready")
                self.level_frame.grid_remove()
                self.update_level(0)
                self.update_action_button(running=False)
                if callable(after):
                    after()

            self.root.after(0, done)

        threading.Thread(target=finalize, daemon=True).start()

    def hotkey_toggle(self):
        if self.transcriber is None:
            self.set_mode(load_runtime_config(CONFIG_FILE).last_mode, force=True)
            self.start()
        elif self.mode_var.get() == "listen":
            self.hotkey_start_mode("speak")
        else:
            self.hotkey_start_mode("listen")

    def hotkey_start_mode(self, mode):
        if self.transcriber is None:
            self.set_mode(mode, force=True)
            self.start()
            return
        if self.mode_var.get() == mode:
            return
        self.stop(after=lambda: (self.set_mode(mode, force=True), self.start()))

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
        ):
            widget.configure(state=combo_state)
        for widget in (
            self.btn_refresh_listen,
            self.btn_refresh_speak,
            self.settings_button,
            self.listen_mode_button,
            self.speak_mode_button,
        ):
            widget.configure(state=normal_state)
        self._set_settings_controls_state(not locked)

    def _set_settings_controls_state(self, enabled):
        for widget in self.settings_controls:
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="readonly" if enabled else "disabled")
                else:
                    widget.configure(state="normal" if enabled else "disabled")
            except tk.TclError:
                pass

    def update_action_button(self, running=False, loading=False):
        button = self.speak_action_button if self.mode_var.get() == "speak" else self.listen_action_button
        other = self.listen_action_button if button is self.speak_action_button else self.speak_action_button
        other.configure(state="disabled" if running or loading else "normal")
        if loading:
            button.configure(text="Please wait…", style="Mac.TButton", state="disabled")
        elif running:
            button.configure(text="■  Stop", style="Stop.TButton", state="normal")
        else:
            symbol = "●" if self.mode_var.get() == "speak" else "▶"
            button.configure(text=f"{symbol}  Start", style="Primary.TButton", state="normal")

    # ------------------------------------------------------------------
    # Status, transcript, and model progress

    def on_event(self, event_type, payload):
        def handle():
            if event_type == "status":
                self.set_status(self.pretty_status(str(payload)))
            elif event_type == "model_progress":
                self.handle_model_progress(payload or {})
            elif event_type == "hint":
                self.show_hint(str(payload))
            elif event_type == "error":
                self.show_error(str(payload))
                self.set_status("Error")
            elif event_type == "transcript":
                self.append_transcript_card(payload or {})
            elif event_type == "level":
                self.update_level(float((payload or {}).get("peak", 0)))

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

    def set_status(self, status):
        self.current_status = status
        self.status_var.set(status)
        color = {
            "Ready": COLORS["tertiary"],
            "Loading models": COLORS["orange"],
            "Listening": COLORS["green"],
            "Transcribing": COLORS["blue"],
            "Translating": COLORS["blue"],
            "Speaking": COLORS["purple"],
            "No audio": COLORS["orange"],
            "Stopping": COLORS["orange"],
            "Error": COLORS["red"],
        }.get(status, COLORS["secondary"])
        self.status_dot.itemconfigure("dot", fill=color)
        self.refresh_tray_menu()

    def handle_model_progress(self, payload):
        phase = str(payload.get("phase", ""))
        fraction = payload.get("fraction")
        self.phase_var.set(phase)
        self.progress.grid(row=0, column=2, padx=(12, 8), sticky="w")
        self.phase_label.grid(row=0, column=3, sticky="w")
        if fraction is None:
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress_var.set(max(0, min(100, float(fraction) * 100)))

    def update_level(self, peak):
        peak = max(0.0, min(1.0, float(peak)))
        self.level_canvas.coords("level", 0, 0, 110 * peak, 8)
        self.peak_var.set(f"peak {peak:.4f}")

    def show_hint(self, message):
        self.hint_var.set(message)
        self.hint_frame.pack(fill="x")

    def show_error(self, message):
        self.error_var.set(message)
        self.error_frame.pack(fill="x")

    def hide_banners(self):
        self.hint_frame.pack_forget()
        self.error_frame.pack_forget()
        self.hint_var.set("")
        self.error_var.set("")

    def append_transcript_card(self, entry):
        self.transcript_entries.append(entry)
        card_bg = COLORS["surface_2"]
        card = tk.Frame(
            self.transcript_scroll.content,
            bg=card_bg,
            highlightbackground=COLORS["separator"],
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        card.pack(fill="x", padx=12, pady=(10 if len(self.transcript_entries) == 1 else 0, 10))

        header = tk.Frame(card, bg=card_bg)
        header.pack(fill="x", pady=(0, 4))
        timestamp = entry.get("timestamp", "")
        try:
            time_text = datetime.fromisoformat(timestamp).strftime("%H:%M:%S")
        except Exception:
            time_text = datetime.now().strftime("%H:%M:%S")
        tk.Label(
            header,
            text=time_text,
            bg=card_bg,
            fg=COLORS["secondary"],
            font=("Cascadia Mono", 8),
        ).pack(side="left")
        source_info = self.current_source_info(entry)
        tk.Label(
            header,
            text=source_info,
            bg=card_bg,
            fg=COLORS["tertiary"],
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(9, 0))

        source_text = entry.get("source_text", entry.get("arabic_text", ""))
        translated_text = entry.get("translated_text", entry.get("english_text", ""))
        self.latest_translation = translated_text or source_text
        source_language = entry.get("source_language", "")
        target_language = entry.get("target_language", "")
        source_anchor = "e" if source_language in RTL_LANGUAGES else "w"
        target_anchor = "e" if target_language in RTL_LANGUAGES else "w"
        source_label = tk.Label(
            card,
            text=source_text,
            bg=card_bg,
            fg=COLORS["text"],
            anchor=source_anchor,
            justify="right" if source_anchor == "e" else "left",
            wraplength=800,
            font=("Segoe UI", 10),
        )
        source_label.pack(fill="x")
        self.transcript_text_labels.append(source_label)
        if translated_text:
            translated_label = tk.Label(
                card,
                text=translated_text,
                bg=card_bg,
                fg=COLORS["secondary"],
                anchor=target_anchor,
                justify="right" if target_anchor == "e" else "left",
                wraplength=800,
                font=("Segoe UI", 10),
            )
            translated_label.pack(fill="x", pady=(5, 0))
            self.transcript_text_labels.append(translated_label)
        self.update_transcript_state()
        self.refresh_tray_menu()
        self.root.after(10, lambda: self.transcript_scroll.canvas.yview_moveto(1.0))

    def current_source_info(self, entry):
        mode = entry.get("mode", self.mode_var.get())
        if mode == "speak":
            choice = self.selected_speak_mic_choice()
        else:
            choice = self.selected_listen_choice()
        device = choice.name if choice else ("Microphone" if mode == "speak" else "Audio")
        return f"{device} · {mode.title()}"

    def update_transcript_state(self):
        count = len(self.transcript_entries)
        self.entry_count_var.set(f"{count} entry" if count == 1 else f"{count} entries")
        state = "normal" if count else "disabled"
        self.clear_button.configure(state=state)
        self.save_button.configure(state=state)
        if count:
            self.empty_state.grid_remove()
            self.transcript_scroll.grid()
        else:
            self.transcript_scroll.grid_remove()
            self.empty_state.grid(row=0, column=0, sticky="new", padx=24, pady=(56, 0))

    def clear_transcript(self):
        self.transcript_entries.clear()
        self.transcript_text_labels.clear()
        for child in self.transcript_scroll.content.winfo_children():
            child.destroy()
        if self.transcriber is not None:
            self.transcriber.transcripts.clear()
        if self.last_transcriber is not None:
            self.last_transcriber.transcripts.clear()
        self.update_transcript_state()
        self.latest_translation = ""
        self.refresh_tray_menu()

    def save_transcript(self):
        transcriber = self.transcriber or self.last_transcriber
        if transcriber is None or not self.transcript_entries:
            return
        transcriber.transcript_folder = self.transcript_folder_var.get()
        saved = transcriber.save_transcript()
        if saved:
            self.last_saved_path = saved
            self.show_hint(f"Transcript saved to {saved}")

    def reveal_transcripts(self):
        folder = Path(self.transcript_folder_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            return
        saved = Path(self.last_saved_path) if self.last_saved_path else None
        if saved and saved.exists():
            subprocess.Popen(["explorer", "/select,", str(saved)])
        else:
            os.startfile(folder)

    def download_models(self):
        self.preload_current_models(force_online=True)

    def preload_current_models(self, force_online=False):
        if self.preview_mode or self.transcriber is not None:
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
        self.set_status("Loading models")

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
                self.root.after(0, lambda: self.set_status("Ready"))
            except Exception as exc:
                self.root.after(0, lambda exc=exc: self.show_error(f"Model preload failed: {exc}"))
                self.root.after(0, lambda: self.set_status("Ready"))
            finally:
                self.root.after(0, self.finish_model_progress)

        threading.Thread(target=run_preload, daemon=True).start()

    def finish_model_progress(self):
        self.progress.stop()
        self.progress.grid_remove()
        self.phase_label.grid_remove()
        self.phase_var.set("")

    # ------------------------------------------------------------------
    # Login and hotkeys

    def toggle_login(self):
        desired = self.login_var.get()
        ok, message = set_open_at_login(desired)
        actual = is_open_at_login_enabled()
        self.login_var.set(actual)
        if not ok:
            messagebox.showerror(
                "Open at login", message, parent=self.settings_window or self.root
            )

    def record_hotkey(self, action):
        self.recording_action = action
        self.set_status(f"Press keys for {HOTKEY_LABELS[action]}")

    def on_key_press(self, event):
        if not self.recording_action:
            return
        combo = format_tk_key_event(event)
        if not combo:
            return
        self.hotkey_vars[self.recording_action].set(combo)
        self.recording_action = None
        self.save_hotkeys_from_ui()
        self.set_status("Ready")

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
        if self.preview_mode:
            return
        hotkeys = {action: variable.get() for action, variable in self.hotkey_vars.items()}
        self.hotkey_manager.register(hotkeys)

    # ------------------------------------------------------------------
    # Windows notification-area counterpart to the macOS MenuBarExtra

    def setup_tray(self):
        try:
            import pystray
            from PIL import Image

            image = Image.open(app_resource_path("Translito.ico")).convert("RGBA")
            menu = pystray.Menu(
                pystray.MenuItem(
                    lambda _item: self.current_status,
                    None,
                    enabled=False,
                ),
                pystray.MenuItem(
                    lambda _item: self.tray_latest_text(),
                    None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda _item: "Stop" if self.transcriber is not None else "Start Listening",
                    lambda _icon, _item: self.root.after(0, self.tray_primary_action),
                ),
                pystray.MenuItem(
                    "Start Speak Mode",
                    lambda _icon, _item: self.root.after(0, self.tray_start_speak),
                    visible=lambda _item: self.transcriber is None,
                ),
                pystray.MenuItem(
                    "Open Translito Window",
                    lambda _icon, _item: self.root.after(0, self.show_main_window),
                    default=True,
                ),
                pystray.MenuItem(
                    "Save Transcript",
                    lambda _icon, _item: self.root.after(0, self.save_transcript),
                    enabled=lambda _item: bool(self.transcript_entries),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Settings…",
                    lambda _icon, _item: self.root.after(0, self.show_settings_from_tray),
                ),
                pystray.MenuItem(
                    "Quit",
                    lambda _icon, _item: self.root.after(0, self.quit_app),
                ),
            )
            self.tray_icon = pystray.Icon("Translito", image, APP_NAME, menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as exc:
            self.tray_icon = None
            self.show_hint(f"Notification-area controls are unavailable: {exc}")

    def tray_latest_text(self):
        if not self.latest_translation:
            return "No transcript yet"
        text = " ".join(self.latest_translation.split())
        return text if len(text) <= 72 else text[:69] + "…"

    def refresh_tray_menu(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def tray_primary_action(self):
        if self.transcriber is not None:
            self.stop()
        else:
            self.set_mode("listen", force=True)
            self.start()

    def tray_start_speak(self):
        if self.transcriber is None:
            self.set_mode("speak", force=True)
            self.start()

    def show_main_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def show_settings_from_tray(self):
        self.show_main_window()
        self.open_settings()

    def quit_app(self):
        self.is_quitting = True
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        if hasattr(self, "hotkey_manager"):
            self.hotkey_manager.unregister()
        if self.transcriber is not None:
            self.stop(after=self.root.destroy)
        else:
            self.root.destroy()

    def on_close(self):
        if self.tray_icon is not None and not self.is_quitting:
            self.root.withdraw()
            return
        self.quit_app()


def gui_main():
    failure_message = dependency_failure_message()
    if failure_message:
        show_startup_error(f"{APP_NAME} startup error", failure_message)
        return

    require_dependencies()
    hide_console_window()
    root = tk.Tk()
    TranslatorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    gui_main()
