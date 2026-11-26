from ui_scale import px, scaled_geometry
from ui_scale import px, scaled_geometry
import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__" and sys.argv[1:2] == ["--check-runtime"]:
    from runtime_check import check_main

    raise SystemExit(check_main(sys.argv[2:]))

if __name__ == "__main__" and sys.argv[1:2] == ["--download-job"]:
    from engines.downloads import download_child
    raise SystemExit(download_child(sys.argv[2]))

import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk

from native_tls import configure_native_tls

configure_native_tls()

from app_config import (
    CONFIG_FILE,
    ConversationConfig,
    DEFAULT_HOTKEYS,
    default_transcript_folder,
    load_device_config,
    load_hotkey_config,
    load_language_config,
    load_conversation_config,
    migrate_conversation_config,
    load_runtime_config,
    load_speak_config,
    load_transcript_folder,
    save_device_config,
    save_hotkey_config,
    save_language_config,
    save_conversation_config,
    save_runtime_config,
    save_speak_config,
    save_transcript_folder,
)
from device_utils import (
    first_real_microphone,
    first_virtual_output,
    query_input_devices,
    query_output_devices,
    same_physical_device,
)
from hotkeys import GlobalHotkeyManager, format_tk_key_event
from engines.display import display_text, dominant_rtl, configure_language_text, refresh_language_text
from engines.mt_local import UnsupportedPairError, resolve_local_mt
from engines.asr_codeswitch import CODESWITCH_REPO
from engines.settings import load_engine_settings, migrate_engine_settings, save_engine_settings
from login import is_open_at_login_enabled, set_open_at_login
from main import ArabicAudioTranscriber, dependency_failure_message, require_dependencies, torch
from model_loading import GLOBAL_MODEL_MANAGER
from speech_output import LocalSpeechSynthesizer
from virtual_mic_ui import VirtualMicSetup


APP_NAME = "Translito"
ENGINE_PROFILES = {"Free (recommended)": "free", "Offline (private)": "offline", "Custom": "custom",
                   "Live interpreter (Gemini preview)": "live-preview"}

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
    "red_hover": "#ff5f56",
    "green": "#30d158",
    "orange": "#ff9f0a",
    "purple": "#bf5af2",
    "yellow_bg": "#3a3320",
    "green_bg": "#203629",
    "red_bg": "#3a2424",
    "blue_bg": "#16293f",
    "on_accent": "#ffffff",
    "black": "#000000",
    "desktop": "#0f1114",
}

from engines.languages import gui_entries, RTL_CODES, pair_default_variety, language as catalog_language
LANGUAGES = gui_entries()

WHISPER_MODELS = [
    "openai/whisper-tiny",
    "openai/whisper-base",
    "openai/whisper-small",
    "openai/whisper-medium",
    "openai/whisper-large-v3",
    "openai/whisper-large-v3-turbo",
    CODESWITCH_REPO,
]

HOTKEY_LABELS = {
    "toggle": "Toggle Listen / Speak",
    "listen": "Start Listening",
    "speak": "Start Speaking",
    "stop": "Stop",
    "subtitles": "Show or hide subtitles",
    "replies": "Suggest replies",
    "reply_1": "Say reply 1",
    "reply_2": "Say reply 2",
    "reply_3": "Say reply 3",
}

RTL_LANGUAGES = RTL_CODES


def translation_model_for(source_code, target_code, *, cloud_available=False):
    if source_code != target_code:
        from engines.mt_translategemma import gemma_available
        if gemma_available(source_code, target_code):
            return f"translategemma:{source_code}:{target_code}"
    try:
        return resolve_local_mt(source_code, target_code, offline=True).model_id
    except UnsupportedPairError:
        if cloud_available:
            return f"cloud:{source_code}:{target_code}"
        raise


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
            f"{px(1)}x{px(1)}+{error_root.winfo_screenwidth() // 2}+{error_root.winfo_screenheight() // 2}"
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


def dialog_parent(app):
    """Use the visible settings window as the owner of its child dialogs."""
    settings = getattr(app, "settings_window", None)
    try:
        if settings is not None and settings.winfo_exists() and settings.winfo_viewable():
            return settings
    except tk.TclError:
        pass
    return app.root


def window_work_area(window, parent=None):
    """Return the selected monitor's usable area, excluding the taskbar."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            class MonitorInfo(ctypes.Structure):
                _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                            ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
            user32 = ctypes.windll.user32
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            owner = parent if parent is not None else window
            monitor = user32.MonitorFromWindow(owner.winfo_id(), 2)
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.work.left, info.work.top, info.work.right, info.work.bottom
        except (AttributeError, OSError, tk.TclError):
            pass
    left, top = window.winfo_vrootx(), window.winfo_vrooty()
    return left, top, left + window.winfo_vrootwidth(), top + window.winfo_vrootheight()


def center_window(window, parent=None, width=None, height=None):
    """Center a Tk window over its visible parent, or over the current screen."""
    window.update_idletasks()
    width = int(px(width) if width is not None else window.winfo_width() if window.winfo_width() > 1 else window.winfo_reqwidth())
    height = int(px(height) if height is not None else window.winfo_height() if window.winfo_height() > 1 else window.winfo_reqheight())

    parent_is_visible = False
    if parent is not None:
        try:
            parent.update_idletasks()
            parent_is_visible = bool(parent.winfo_exists() and parent.winfo_viewable())
        except tk.TclError:
            parent_is_visible = False

    screen_left, screen_top, screen_right, screen_bottom = window_work_area(window, parent if parent_is_visible else None)
    if parent_is_visible:
        # Top-level geometry coordinates refer to the decorated window frame,
        # while winfo_root* points at the client area below the title bar.
        # Using winfo_x/y keeps the outer Windows frames truly concentric.
        x = parent.winfo_x() + (parent.winfo_width() - width) // 2
        y = parent.winfo_y() + (parent.winfo_height() - height) // 2
    else:
        x = screen_left + (screen_right - screen_left - width) // 2
        y = screen_top + (screen_bottom - screen_top - height) // 2
    # A larger dialog centered over a parent near a screen edge can otherwise
    # start outside the desktop, hiding its controls even when its size fits.
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
            highlightthickness=px(0),
            borderwidth=px(0),
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
        self._fit_content_width()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_content_width(self, _event=None):
        # Hidden pages can receive queued Configure events after being resized.
        # Use the current canvas size rather than a stale event's old width.
        width = self.canvas.winfo_width()
        if width > 1 and int(float(self.canvas.itemcget(self.window_id, "width"))) != width:
            self.canvas.itemconfigure(self.window_id, width=width)

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
            height=px(24),
            bg=background or COLORS["surface"],
            highlightthickness=px(0),
            borderwidth=px(0),
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
        left, right = px(7), max(px(8), self.winfo_width() - px(7))
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
        left, right, center = px(7), max(px(8), width - px(7)), px(12)
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
            width=px(4),
            capstyle="round",
            tags="scale",
        )
        self.create_line(
            left,
            center,
            thumb_x,
            center,
            fill=accent,
            width=px(4),
            capstyle="round",
            tags="scale",
        )
        self.create_oval(
            thumb_x - px(6),
            center - px(6),
            thumb_x + px(6),
            center + px(6),
            fill=accent,
            outline=COLORS["surface_2"],
            width=px(1),
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
        import queue
        self._ui_events = queue.Queue()
        self.root.after(50, self._drain_ui)
        from tk_lifecycle import confine_tk_collection
        confine_tk_collection(root)
        self.root.title(APP_NAME)
        self.root.geometry(scaled_geometry("800x640"))
        self.root.minsize(px(640), px(480))
        self.root.configure(bg=COLORS["bg"])
        self.preview_mode = os.environ.get("TRANSLITO_UI_PREVIEW", "0").strip() == "1"
        self._initializing = True
        self.tray_mode = "--tray" in sys.argv
        if self.tray_mode:
            self.root.withdraw()

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
        self.model_setup_busy = False
        self.last_transcriber = None
        self.last_saved_path = None
        self.transcript_entries = []
        self.transcript_targets = {}
        self.transcript_meta = {}
        self.transcript_text_labels = []
        self.recording_action = None
        self.settings_window = None
        self.settings_controls = []
        self.tray_icon = None
        self.is_quitting = False
        self.current_status = "Ready"
        self.latest_translation = ""
        self.synthesizer = LocalSpeechSynthesizer()

        if not self.preview_mode:
            from settings_store import SettingsStore
            SettingsStore(CONFIG_FILE).migrate(language_code=lambda value: next((iso for name, bcp, iso in LANGUAGES if value in {name, iso}), value))
        language_config = load_language_config(CONFIG_FILE)
        speak_config = load_speak_config(CONFIG_FILE)
        runtime_config = load_runtime_config(CONFIG_FILE)
        engines = load_engine_settings(CONFIG_FILE) if self.preview_mode else migrate_engine_settings(CONFIG_FILE)
        conversation = (load_conversation_config(CONFIG_FILE) if self.preview_mode else
                        migrate_conversation_config(CONFIG_FILE))
        hotkeys = load_hotkey_config(CONFIG_FILE)

        env_offline = os.environ.get("OFFLINE_ONLY")
        offline_default = (
            env_offline.strip() == "1" if env_offline is not None else runtime_config.offline_only
        ) or engines.profile == "offline"
        self.engine_profile_var = tk.StringVar(value=("Offline (private)" if offline_default else
            next((label for label, value in ENGINE_PROFILES.items() if value == engines.profile), "Free (recommended)")))
        self.mode_var = tk.StringVar(value=runtime_config.last_mode)
        self.listen_device_var = tk.StringVar(value="")
        self.listen_source_type_var = tk.StringVar(value="Device")
        self.speak_mic_var = tk.StringVar(value=speak_config.mic_name)
        self.speak_output_var = tk.StringVar(value=speak_config.output_device_name)
        self._auto_select_speak_output = True
        self.listen_source_var = tk.StringVar(value=self.language_name_for_iso(language_config.source))
        self.listen_target_var = tk.StringVar(value=self.language_name_for_iso(language_config.target))
        self.speak_source_var = tk.StringVar(value=self.language_name_for_iso(speak_config.source))
        self.speak_target_var = tk.StringVar(value=self.language_name_for_iso(speak_config.target))
        self.whisper_var = tk.StringVar(value=language_config.whisper_model)
        self.quality_var = tk.StringVar(value=runtime_config.asr_preset.title())
        self.conversation_other_var = tk.StringVar(value=self.language_name_for_iso(conversation.other_language))
        self.my_language_var = tk.StringVar(value=self.language_name_for_iso(conversation.my_language))
        self.audience_language_var = tk.StringVar(value=self.language_name_for_iso(conversation.audience_language))
        self.both_languages_var = tk.BooleanVar(value=conversation.show_both)
        self.keep_english_var = tk.BooleanVar(value=conversation.keep_english_terms)
        self.same_language_speech_var = tk.StringVar(value={"passthrough": "Pass my voice through",
            "voice": "Read it with the voice", "mute": "Mute"}[conversation.same_language_speech])
        self.one_way_var = tk.BooleanVar(value=conversation.one_way)
        self.engine_var = tk.StringVar(value="Engine  On this PC")
        self.lag_var = tk.StringVar(value="")
        self.active_engines = {"asr": "Local", "mt": "Local"}
        self.active_fallbacks = {"asr": False, "mt": False}
        self.offline_only_var = tk.BooleanVar(value=__import__("app_config").read_config(CONFIG_FILE).getboolean("NETWORK", "block_all", fallback=False))
        self.monitor_var = tk.BooleanVar(value=speak_config.monitor_spoken_audio)
        self.voice_var = tk.StringVar(value=speak_config.voice or "Automatic")
        self.voice_hint_var = tk.StringVar(value="")
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

        from settings_state import SettingsState, CONTROL_VARIABLES
        self.preferences = SettingsState(CONFIG_FILE, writable=lambda: not self.preview_mode and not self._initializing)
        self.preferences.owner = self
        for name in CONTROL_VARIABLES:
            self.preferences.bind_control(self, name)
        self._capture_source_type = self.listen_source_type_var.get()
        for action, var in self.hotkey_vars.items():
            self.preferences.bind(var, "HOTKEYS", action, var.get())
        geometry = self.preferences.get("UI", "window_geometry", "800x640")
        import re
        if re.fullmatch(r"\d{3,4}x\d{3,4}(?:[+-]\d+[+-]\d+)?", geometry):
            from ui_scale import restore_geometry
            self.root.geometry(restore_geometry(geometry, self.preferences.get("UI", "window_dpi", 96)))

        self.english_passthrough_var = self.preferences.bind(tk.BooleanVar(value=not conversation.one_way),
            "LANGUAGE", "english_passthrough", not conversation.one_way)
        self.variety_var = self.preferences.bind(tk.StringVar(), "LANGUAGE", "variety",
            pair_default_variety(language_config.source,language_config.target))
        if not self.variety_var.get():
            self.variety_var.set(pair_default_variety(language_config.source,language_config.target))

        self.subtitles_enabled_var = self.preferences.bind(tk.BooleanVar(), "UI", "subtitles_enabled", False)
        self.delay_var = tk.StringVar(value="Delay —")
        self.session_cost_var = tk.StringVar(value="Session $0.00")
        self.month_cost_var = tk.StringVar(value="This month $0.00")
        from engine_ui import initialize as initialize_engine_controls
        initialize_engine_controls(self)
        from meeting_app import initialize as initialize_meeting_app
        initialize_meeting_app(self)
        self.apply_styles()
        self.build_ui()
        from engine_ui import refresh_measurements
        refresh_measurements(self)
        self.bind_events()
        self.update_conversation_controls(persist=False)

        self.hotkey_manager = GlobalHotkeyManager(
            callbacks={
                "toggle": lambda: self.post_ui( self.hotkey_toggle),
                "listen": lambda: self.post_ui( lambda: self.hotkey_start_mode("listen")),
                "speak": lambda: self.post_ui( lambda: self.hotkey_start_mode("speak")),
                "stop": lambda: self.post_ui( self.stop),
                "subtitles": lambda: self.post_ui( self.toggle_subtitles),
                "replies": lambda: self.post_ui( self.reply_controller.show_and_request),
                **{f"reply_{i+1}": lambda i=i: self.post_ui(lambda:self.reply_controller.say(i)) for i in range(3)},
            },
            on_error=lambda message: self.post_ui( lambda: self.show_error(message)),
        )
        if not self.preview_mode:
            from login import migrate_startup_command
            migrate_startup_command()
            self.register_hotkeys()
            self.setup_tray()

        self.refresh_devices(show_error=not self.preview_mode)
        self.set_mode("listen", force=True)
        self.refresh_voices()
        self.update_noise_gate_label()
        self.update_chunk_label()
        self.update_transcript_state()
        from subtitle_overlay import SubtitleController
        self.subtitle_controller = SubtitleController(self, COLORS)
        from schedule_ui import ScheduleController
        self.schedule_controller = ScheduleController(self, COLORS)
        from reply_ui import ReplyController
        self.reply_controller = ReplyController(self, COLORS)
        from download_ui import initialize as initialize_downloads
        initialize_downloads(self, COLORS)
        from session_ui import SessionController
        self.session_controller = SessionController(self)
        self._initializing = False
        center_window(self.root)
        if not self.preview_mode:
            self.root.after(350, self.preload_current_models)
            self.root.after(3000, self.auto_refresh_devices)
            self.root.after(1000, self.refresh_cost_status)
            if not self.tray_mode and not self.preferences.get("CAPTURE", "default_app_prompted", False):
                self.preferences.set("CAPTURE", "default_app_prompted", True)
                self.root.after(600, lambda: self.show_hint("Choose your default meeting app in Settings → Audio."))

    # ------------------------------------------------------------------
    # Window construction

    def post_ui(self, callback):
        from ui_dispatch import post
        post(self, callback)

    def _drain_ui(self):
        import queue
        for _ in range(200):
            try:
                callback = self._ui_events.get_nowait()
            except queue.Empty:
                break
            callback()
        try:
            if self.root.winfo_exists():
                self.root.after(50, self._drain_ui)
        except tk.TclError:
            pass

    def apply_styles(self):
        from ui_theme import apply_theme
        self.style = ttk.Style(self.root)
        apply_theme(self.root, self.style, COLORS)

    def build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(8, weight=1)

        self.mode_bar = tk.Frame(self.root, bg=COLORS["bg"], height=px(48))
        self.mode_bar.grid(row=0, column=0, sticky="ew")
        self.mode_bar.columnconfigure(0, weight=1)
        segment = tk.Frame(
            self.mode_bar,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=px(1),
        )
        segment.grid(row=0, column=0, sticky="w", padx=px(12), pady=px((10, 4)))
        self.listen_mode_button = ttk.Button(
            segment,
            text="Listen",
            style="SegmentActive.TButton",
            command=lambda: self.set_mode("listen"),
        )
        self.listen_mode_button.pack(side="left")
        self.speak_mode_button = ttk.Button(
            segment,
            text="Speak",
            style="SegmentInactive.TButton",
            command=lambda: self.set_mode("speak"),
        )
        self.speak_mode_button.pack(side="left")
        subtitle_controls = tk.Frame(self.mode_bar, bg=COLORS["bg"])
        subtitle_controls.grid(row=0, column=1, sticky="e", pady=px((10, 4)))
        tk.Label(subtitle_controls, text="Subtitles on screen", bg=COLORS["bg"], fg=COLORS["secondary"],
                 font=("Segoe UI", 9)).pack(side="left", padx=px((0, 8)))
        from ui_widgets import Switch
        self.subtitle_switch = Switch(subtitle_controls, self.subtitles_enabled_var, COLORS)
        self.subtitle_switch.pack(side="left")
        from PIL import Image, ImageTk
        icon = Image.open(app_resource_path("engines/data/ui/settings.png"))
        self.settings_image = ImageTk.PhotoImage(icon.resize((px(15), px(15)), Image.Resampling.LANCZOS), master=self.root)
        self.settings_button = ttk.Button(
            self.mode_bar,
            image=self.settings_image,
            width=px(2, chars=True),
            style="Icon.TButton",
            command=self.open_settings,
        )
        self.settings_button.grid(row=0, column=2, sticky="e", padx=px(12), pady=px((10, 4)))

        self._separator(1)

        self.controls_host = tk.Frame(self.root, bg=COLORS["bg"])
        self.controls_host.grid(row=2, column=0, sticky="ew")
        self.controls_host.columnconfigure(0, weight=1)
        self.listen_frame = self._build_listen_controls(self.controls_host)
        self.speak_frame = self._build_speak_controls(self.controls_host)

        self.virtual_mic_setup = VirtualMicSetup(self, COLORS)
        self.routing_banner = self.virtual_mic_setup.frame
        self.routing_label = self.virtual_mic_setup.label

        self._separator(4)
        self._build_status_bar()
        self._build_banners()
        self._separator(7)
        self._build_transcript_area()
        self._build_bottom_bar()

    def _separator(self, row):
        tk.Frame(self.root, bg=COLORS["separator"], height=px(1)).grid(
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
        ).pack(fill="x", pady=px((0, 3)))
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
        frame = tk.Frame(parent, bg=COLORS["bg"], padx=px(12), pady=px(10))
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(0, weight=3)
        frame.columnconfigure(2, weight=2)
        frame.columnconfigure(3, weight=2)

        source_field, self.listen_combo = self._field(
            frame, "Source", self.listen_device_var, width=px(26)
        )
        source_field.pack_slaves()[0].destroy()
        capture_switch = tk.Frame(source_field, bg=COLORS["bg"])
        capture_switch.pack(fill="x", before=self.listen_combo, pady=px((0, 4)))
        self.capture_kind_buttons = {}
        for kind in ("App audio", "Device"):
            button = ttk.Button(capture_switch, text=kind, width=px(9, chars=True),
                command=lambda selected=kind:self.select_capture_source(selected))
            button.pack(side="left")
            self.capture_kind_buttons[kind] = button
        self.listen_source_type_var.trace_add("write", lambda *_:self.update_capture_switch())
        self.update_capture_switch()
        source_field.grid(row=0, column=0, sticky="ew", padx=px((0, 10)))
        self.btn_refresh_listen = ttk.Button(
            frame, text="↻", width=px(2, chars=True), style="Icon.TButton", command=self.manual_refresh_devices
        )
        self.btn_refresh_listen.grid(row=0, column=1, sticky="s", padx=px((0, 10)))

        from_field, self.listen_source_combo = self._field(
            frame, "English +", self.conversation_other_var, width=px(12)
        )
        self.listen_source_label = from_field.winfo_children()[0]
        self.listen_source_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        from_field.grid(row=0, column=2, sticky="sew", padx=px((0, 10)))

        to_field, self.listen_target_combo = self._field(
            frame, "My language", self.my_language_var, width=px(12)
        )
        self.listen_target_label = to_field.winfo_children()[0]
        self.listen_target_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        to_field.grid(row=0, column=3, sticky="sew", padx=px((0, 12)))

        self.listen_action_button = ttk.Button(
            frame,
            text="▶  Start",
            width=px(9, chars=True),
            style="Primary.TButton",
            command=self.toggle_capture,
        )
        self.listen_action_button.grid(row=0, column=4, sticky="s")
        self.app_audio_hint = tk.Label(frame, text="", bg=COLORS["bg"], fg=COLORS["secondary"], font=("Segoe UI", 8), anchor="w")
        return frame

    def _build_speak_controls(self, parent):
        frame = tk.Frame(parent, bg=COLORS["bg"], padx=px(12), pady=px(10))
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=2)
        frame.columnconfigure(3, weight=1)
        frame.columnconfigure(4, weight=1)

        mic_field, self.speak_mic_combo = self._field(
            frame, "Microphone", self.speak_mic_var, width=px(13)
        )
        mic_field.grid(row=0, column=0, sticky="ew", padx=px((0, 10)))

        output_field, self.speak_output_combo = self._field(
            frame, "Speak to", self.speak_output_var, width=px(13)
        )
        output_field.grid(row=0, column=1, sticky="ew", padx=px((0, 10)))

        self.btn_refresh_speak = ttk.Button(
            frame, text="↻", width=px(2, chars=True), style="Icon.TButton", command=self.manual_refresh_devices
        )
        self.btn_refresh_speak.grid(row=0, column=2, sticky="s", padx=px((0, 10)))

        from_field, self.speak_source_combo = self._field(
            frame, "English +", self.conversation_other_var, width=px(8)
        )
        self.speak_source_label = from_field.winfo_children()[0]
        self.speak_source_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        from_field.grid(row=0, column=3, sticky="ew", padx=px((0, 10)))

        to_field, self.speak_target_combo = self._field(
            frame, "Audience", self.audience_language_var, width=px(8)
        )
        self.speak_target_label = to_field.winfo_children()[0]
        self.speak_target_combo["values"] = [name for name, _bcp, _iso in LANGUAGES]
        to_field.grid(row=0, column=4, sticky="ew", padx=px((0, 12)))

        self.speak_action_button = ttk.Button(
            frame,
            text="●  Start",
            width=px(9, chars=True),
            style="Primary.TButton",
            command=self.toggle_capture,
        )
        self.speak_action_button.grid(row=0, column=5, sticky="s")
        ttk.Button(frame, text="Virtual-mic setup…", style="Mac.TButton",
                   command=self.show_virtual_mic_setup).grid(row=1, column=0, columnspan=2, sticky="w", pady=px((6, 0)))
        return frame

    def _build_status_bar(self):
        self.status_bar = tk.Frame(self.root, bg=COLORS["bg"], padx=px(12), pady=px(8))
        self.status_bar.grid(row=5, column=0, sticky="ew")
        self.status_bar.columnconfigure(4, weight=1)

        self.status_dot = tk.Canvas(
            self.status_bar,
            width=px(14),
            height=px(14),
            bg=COLORS["bg"],
            highlightthickness=px(0),
        )
        self.status_dot.create_oval(2, 2, 12, 12, fill=COLORS["tertiary"], outline="", tags="dot")
        self.status_dot.grid(row=0, column=0, padx=px((0, 8)))
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
            length=px(125),
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
        ).pack(side="left", padx=px((0, 5)))
        self.level_canvas = tk.Canvas(
            self.level_frame,
            width=px(110),
            height=px(8),
            bg=COLORS["field"],
            highlightthickness=px(0),
        )
        self.level_canvas.create_rectangle(0, 0, 0, px(8), fill=COLORS["green"], outline="", tags="level")
        self.level_canvas.pack(side="left")
        tk.Label(
            self.level_frame,
            textvariable=self.peak_var,
            bg=COLORS["bg"],
            fg=COLORS["tertiary"],
            font=("Cascadia Mono", 8),
        ).pack(side="left", padx=px((6, 0)))
        self.level_frame.grid(row=0, column=5, sticky="e")
        self.level_frame.grid_remove()
        for column, variable in ((2, self.delay_var), (3, self.engine_var), (4, self.session_cost_var), (5, self.month_cost_var)):
            label = tk.Label(self.status_bar, textvariable=variable, bg=COLORS["bg"], fg=COLORS["secondary"],
                             font=("Segoe UI", 8), anchor="w")
            label.grid(row=0, column=column, padx=px((14, 0)), sticky="w")
            if column == 3:
                self.engine_label = label
                label.configure(width=px(24))
        tk.Label(self.status_bar, textvariable=self.lag_var, bg=COLORS["bg"], fg=COLORS["orange"],
                 font=("Segoe UI", 8)).grid(row=1, column=5, sticky="e")


    def _build_banners(self):
        self.banner_host = tk.Frame(self.root, bg=COLORS["bg"])
        self.banner_host.grid(row=6, column=0, sticky="ew")
        self.hint_frame = tk.Frame(self.banner_host, bg=COLORS["yellow_bg"])
        self.hint_icon = tk.Label(
            self.hint_frame,
            text="●",
            bg=COLORS["yellow_bg"],
            fg=COLORS["orange"],
            padx=px(12),
        )
        self.hint_icon.pack(side="left")
        self.hint_label = tk.Label(
            self.hint_frame,
            textvariable=self.hint_var,
            bg=COLORS["yellow_bg"],
            fg=COLORS["secondary"],
            justify="left",
            anchor="w",
            wraplength=px(800),
            pady=px(8),
        )
        self.hint_action = ttk.Button(self.hint_frame, style="Mac.TButton")
        self.hint_label.pack(side="left", fill="x", expand=True, padx=px((0, 12)))

        self.error_frame = tk.Frame(self.banner_host, bg=COLORS["red_bg"])
        self.error_icon = tk.Label(
            self.error_frame,
            text="!",
            bg=COLORS["red_bg"],
            fg=COLORS["red"],
            font=("Segoe UI Semibold", 10),
            padx=px(12),
        )
        self.error_icon.pack(side="left")
        self.error_label = tk.Label(
            self.error_frame,
            textvariable=self.error_var,
            bg=COLORS["red_bg"],
            fg="#ffb4ae",
            justify="left",
            anchor="w",
            wraplength=px(800),
            pady=px(8),
        )
        self.error_label.pack(side="left", fill="x", expand=True, padx=px((0, 12)))

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
            width=px(40),
            height=px(36),
            bg=COLORS["bg"],
            highlightthickness=px(0),
            borderwidth=px(0),
        )
        empty_icon.create_line(
            6, 5, 34, 5, 34, 25, 18, 25, 11, 31, 11, 25, 6, 25, 6, 5,
            fill=COLORS["tertiary"],
            width=px(2),
            joinstyle="round",
        )
        empty_icon.create_line(12, 12, 28, 12, fill=COLORS["tertiary"], width=px(2))
        empty_icon.create_line(12, 18, 24, 18, fill=COLORS["tertiary"], width=px(2))
        from ui_scale import scale
        empty_icon.scale("all", 0, 0, scale(), scale())
        empty_icon.pack(pady=px((0, 8)))
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
            wraplength=px(460),
            font=("Segoe UI", 9),
        )
        self.empty_help_label.pack(pady=px((5, 0)))
        self.empty_measurements_var = tk.StringVar(value="")
        tk.Label(self.empty_state, textvariable=self.empty_measurements_var, bg=COLORS["bg"], fg=COLORS["tertiary"],
                 wraplength=px(460), justify="center", font=("Segoe UI", 9)).pack(pady=px((12, 0)))
        actions = self.empty_actions = tk.Frame(self.empty_state, bg=COLORS["bg"])
        actions.pack(pady=px((12, 0)))
        actions.columnconfigure((0, 1), weight=1, uniform="empty-state-actions")
        self.empty_setup_button = ttk.Button(actions, text="Set up cloud", command=self.open_cloud_setup, style="Mac.TButton")
        self.empty_setup_button.grid(row=0, column=0, sticky="nsew", padx=px((0, 4)))
        def keep_local():
            self.preferences.set("UI", "setup_offer_seen", True)
            self.engine_choice_var.set("local")
            self.session_controller.refresh()
        self.empty_local_button = ttk.Button(actions, text="Keep using this PC", command=keep_local, style="Mac.TButton")
        self.empty_local_button.grid(row=0, column=1, sticky="nsew", padx=px((4, 0)))

    def _build_bottom_bar(self):
        bar = tk.Frame(self.root, bg=COLORS["bg"], padx=px(12), pady=px(12))
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
        self.clear_button.grid(row=0, column=2, padx=px((8, 0)))
        self.save_button = ttk.Button(
            bar, text="Save Transcript", style="Mac.TButton", command=self.save_transcript
        )
        self.save_button.grid(row=0, column=3, padx=px((8, 0)))
        self.show_folder_button = ttk.Button(
            bar, text="Show in Explorer", style="Mac.TButton", command=self.reveal_transcripts
        )
        self.show_folder_button.grid(row=0, column=4, padx=px((8, 0)))

    # ------------------------------------------------------------------
    # Settings window

    def refresh_cost_status(self):
        from engine_ui import refresh_usage
        refresh_usage(self)
        if not self.is_quitting:
            self.root.after(1000, self.refresh_cost_status)

    def toggle_subtitles(self):
        self.subtitle_controller.toggle()

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            center_window(self.settings_window, self.root, 820, 680)
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("Translito Settings")
        window.geometry(scaled_geometry("820x680"))
        window.minsize(px(720), px(460))
        window.resizable(True, True)
        window.configure(bg=COLORS["bg"])
        window.transient(self.root)
        try:
            window.iconbitmap(default=str(app_resource_path("Translito.ico")))
        except tk.TclError:
            pass
        from ui_theme import apply_theme
        apply_theme(window, self.style, COLORS)
        from settings_shell import SettingsShell
        from settings_feedback import add_footer
        add_footer(self, window, COLORS)
        from ui_theme import dark_titlebar
        self.settings_shell = SettingsShell(window, COLORS, ScrollableFrame,
            initial=self.preferences.get("UI", "last_settings_page", "Languages"),
            on_page=lambda page: self.preferences.set("UI", "last_settings_page", page))
        content = self.settings_shell.contents["General"]
        window.after_idle(lambda: dark_titlebar(window))
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
        for action in DEFAULT_HOTKEYS:
            row = tk.Frame(hotkeys, bg=COLORS["surface"])
            row.pack(fill="x", pady=px(3))
            row.columnconfigure(1, weight=1)
            tk.Label(
                row,
                text=HOTKEY_LABELS[action],
                bg=COLORS["surface"],
                fg=COLORS["text"],
                width=px(19, chars=True),
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            entry = tk.Entry(
                row,
                textvariable=self.hotkey_vars[action],
                bg=COLORS["field"],
                fg=COLORS["text"],
                insertbackground=COLORS["text"],
                relief="flat",
                highlightthickness=px(1),
                highlightbackground=COLORS["border"],
                highlightcolor=COLORS["blue"],
            )
            entry.grid(row=0, column=1, sticky="ew", padx=px((8, 8)), ipady=px(6))
            record = ttk.Button(
                row,
                text="Record",
                style="Mac.TButton",
                command=lambda a=action: self.record_hotkey(a),
            )
            record.grid(row=0, column=2, padx=px((0, 6)))
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
        ).pack(anchor="e", pady=px((7, 0)))
        self._settings_help(
            hotkeys,
            "Hotkeys work system-wide. Toggle starts the last-used mode or switches between listening and speaking.",
        )

        languages = self._settings_section(content, "Languages")
        self._settings_help(languages, "What is being spoken and what you want to read.")
        pair = tk.Frame(languages, bg=COLORS["surface"])
        pair.pack(fill="x", pady=px((10, 12)))
        for label, variable in (("Spoken language", self.listen_source_var), ("Translate to", self.listen_target_var)):
            field, combo = self._field(pair, label, variable, width=px(22))
            field.pack(side="left", fill="x", expand=True, padx=px((0, 10)))
            combo.configure(values=[name for name, _, _ in LANGUAGES])
            combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_language_pair())
            self.settings_controls.append(combo)
        from quality_settings import _entry
        _entry(languages, "Variety (optional, for example ar-SA)", self.variety_var, COLORS)
        for text, variable, callback in (
            ("Speakers also use English. Show it as spoken, do not translate.", self.english_passthrough_var, self.apply_language_pair),
            ("Keep English technical terms in English", self.keep_english_var, self.persist_settings),
            ("Show the original line under each translation", self.both_languages_var, self.persist_settings)):
            control = tk.Checkbutton(languages, text=text, variable=variable, command=callback, **self._checkbutton_options())
            control.pack(anchor="w", pady=px(5))
            self.settings_controls.append(control)
        ttk.Button(languages, text="Edit terms", style="Mac.TButton", command=self.open_terms).pack(anchor="w", pady=px(10))

        recognition = self._settings_section(content, "Speech Recognition")
        cohere_button = ttk.Button(recognition, text="Recommended local model", style="Mac.TButton",
                                    command=self.download_models)
        cohere_button.pack(anchor="w", pady=px((3, 8)))
        self.settings_controls.append(cohere_button)
        quality_settings = self._settings_combo(recognition, "Quality", self.quality_var,
                                                ["Fast", "Balanced", "Best"])
        quality_settings.bind("<<ComboboxSelected>>", lambda _event: self.change_quality_preset())
        self._settings_help(recognition, "Cohere Arabic is the recommended recognizer after model setup. "
                            "This preset controls the local Whisper fallback; Best can lag on a CPU.")
        advanced_recognition = tk.Frame(recognition, bg=COLORS["surface"])

        def toggle_advanced_recognition():
            if advanced_recognition.winfo_manager():
                advanced_recognition.pack_forget()
                advanced_recognition_button.configure(text="Advanced ▸")
            else:
                advanced_recognition.pack(fill="x", after=advanced_recognition_button)
                advanced_recognition_button.configure(text="Advanced ▾")

        advanced_recognition_button = ttk.Button(recognition, text="Advanced ▸", style="Mac.TButton",
                                                  command=toggle_advanced_recognition)
        advanced_recognition_button.pack(anchor="w", pady=px(5))
        self.settings_controls.append(advanced_recognition_button)
        whisper_settings = self._settings_combo(
            advanced_recognition, "Model ID", self.whisper_var, WHISPER_MODELS
        )
        whisper_settings.bind("<<ComboboxSelected>>", lambda _event: self.persist_settings())
        slider_row = tk.Frame(advanced_recognition, bg=COLORS["surface"])
        slider_row.pack(fill="x", pady=px(5))
        tk.Label(
            slider_row,
            text="Legacy window",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            width=px(19, chars=True),
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
        chunk_scale.pack(side="left", fill="x", expand=True, padx=px((8, 8)))
        self.chunk_label = tk.Label(
            slider_row,
            text="6 s",
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            width=px(5, chars=True),
            anchor="w",
            font=("Cascadia Mono", 9),
        )
        self.chunk_label.pack(side="left")
        offline = tk.Checkbutton(
            general,
            text="Never connect to the internet (blocks cloud and model downloads)",
            variable=self.offline_only_var,
            command=self.change_offline_mode,
            **self._checkbutton_options(),
        )
        offline.pack(anchor="w", pady=px((6, 2)))
        ttk.Button(
            recognition,
            text="Manage models…",
            style="Mac.TButton",
            command=self.download_models,
        ).pack(anchor="w", pady=px((5, 0)))
        self._settings_help(
            recognition,
            "Models download once, then run locally. Live segments close after a pause, up to 15 seconds. "
            "Legacy window length is used only by the evaluation comparison mode.",
        )
        self.settings_controls.extend((whisper_settings, chunk_scale, offline))

        from download_ui import models_page
        models_page(self, self.settings_shell.contents["Models"], COLORS)
        from engine_ui import pages as build_engine_pages
        build_engine_pages(self, COLORS)
        from subtitle_overlay import build_subtitle_page
        build_subtitle_page(self, COLORS)
        from meeting_app import page as build_meeting_app_page
        build_meeting_app_page(self, COLORS)
        from schedule_ui import page as build_schedule_page
        build_schedule_page(self, COLORS)
        from reply_ui import page as build_reply_page
        build_reply_page(self, COLORS)
        translation = self._settings_section(content, "Local translation")
        gemma_button = ttk.Button(translation, text="Set up TranslateGemma", style="Mac.TButton",
                                   command=self.open_translation_model_setup)
        gemma_button.pack(anchor="w", pady=px((3, 6)))
        self.settings_controls.append(gemma_button)
        self._settings_help(translation, "TranslateGemma 4B offers a larger local translator on PCs with at least 8 GB RAM. "
                            "It is an optional 2.5 GB download. Lite translation is the fallback.")

        capture = self._settings_section(content, "Capture")
        gate_row = tk.Frame(capture, bg=COLORS["surface"])
        gate_row.pack(fill="x", pady=px(5))
        tk.Label(
            gate_row,
            text="Mic noise gate",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            width=px(19, chars=True),
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
        gate_scale.pack(side="left", fill="x", expand=True, padx=px((8, 8)))
        self.noise_gate_label = tk.Label(
            gate_row,
            text="Medium",
            bg=COLORS["surface"],
            fg=COLORS["secondary"],
            width=px(10, chars=True),
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
        self.voice_guidance = tk.Frame(speak, bg=speak.cget("bg"))
        tk.Label(self.voice_guidance, textvariable=self.voice_hint_var, bg=speak.cget("bg"),
                 fg=COLORS["secondary"], font=("Segoe UI", 8), wraplength=px(440),
                 justify="left", anchor="w").pack(fill="x", pady=px((8, 4)))
        ttk.Button(self.voice_guidance, text="Windows speech settings", style="Mac.TButton",
                   command=lambda: webbrowser.open("ms-settings:speech")).pack(anchor="w")
        monitor = tk.Checkbutton(
            speak,
            text="Also play spoken translation through my speakers",
            variable=self.monitor_var,
            command=self.persist_settings,
            **self._checkbutton_options(),
        )
        monitor.pack(anchor="w", pady=px((7, 2)))
        self.voice_settings_monitor = monitor
        if self.voice_hint_var.get():
            self.voice_guidance.pack(fill="x", before=monitor)
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
            padx=px(8),
            pady=px(7),
            wraplength=px(440),
        )
        folder_label.pack(fill="x", pady=px((0, 8)))
        folder_buttons = tk.Frame(transcripts, bg=COLORS["surface"])
        folder_buttons.pack(fill="x")
        ttk.Button(
            folder_buttons, text="Choose Folder…", style="Mac.TButton", command=self.choose_folder
        ).pack(side="left")
        ttk.Button(
            folder_buttons, text="Use Default", style="Mac.TButton", command=self.reset_folder
        ).pack(side="left", padx=px((8, 0)))
        ttk.Button(
            folder_buttons, text="Open Folder", style="Mac.TButton", command=self.open_folder
        ).pack(side="left", padx=px((8, 0)))

        if self.transcriber is not None:
            self._settings_help(content, "Stop capture to change settings.", color=COLORS["orange"])
            self._settings_help(content, "Applies when you start the next session", color=COLORS["orange"])
        self.update_noise_gate_label()
        self.update_chunk_label()
        center_window(window, self.root, 820, 680)
        window.lift()
        window.focus_force()

    def _settings_section(self, parent, title):
        if getattr(self, "settings_shell", None):
            parent = self.settings_shell.section_parent(title)
        outer = tk.Frame(parent, bg=COLORS["bg"])
        outer.pack(fill="x", pady=px((0, 14)))
        tk.Label(
            outer,
            text=title,
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 12),
            anchor="w",
        ).pack(fill="x", padx=px(3), pady=px((0, 5)))
        card = tk.Frame(
            outer,
            bg=COLORS["surface"],
            highlightbackground=COLORS["border"],
            highlightthickness=px(1),
            padx=px(12),
            pady=px(11),
        )
        card.pack(fill="x")
        return card

    def _settings_combo(self, parent, label, variable, values):
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", pady=px(4))
        tk.Label(
            row,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            width=px(19, chars=True),
            anchor="w",
        ).pack(side="left")
        combo = ttk.Combobox(
            row,
            textvariable=variable,
            values=values,
            state="readonly",
            style="Dark.TCombobox",
        )
        combo.pack(side="left", fill="x", expand=True, padx=px((8, 0)))
        self.settings_controls.append(combo)
        # ttk otherwise changes a focused language/provider selection while the
        # user is merely scrolling the settings page.
        combo.bind("<MouseWheel>", lambda _event: "break")
        return combo

    def _settings_help(self, parent, text, color=None):
        tk.Label(
            parent,
            text=text,
            bg=parent.cget("bg"),
            fg=color or COLORS["tertiary"],
            justify="left",
            anchor="w",
            wraplength=px(440),
            font=("Segoe UI", 8),
        ).pack(fill="x", pady=px((8, 0)))

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
            "<<ComboboxSelected>>", lambda event: (self.speak_output_selected(event), self.persist_settings())
        )
        self.listen_source_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_language_pair())
        self.listen_target_combo.bind("<<ComboboxSelected>>", lambda _event: self.apply_language_pair())
        self.speak_source_combo.bind("<<ComboboxSelected>>", lambda _event: self.update_conversation_controls())
        self.speak_target_combo.bind(
            "<<ComboboxSelected>>", lambda _event: (self.refresh_voices(), self.update_conversation_controls())
        )
        self.root.bind_all("<KeyPress>", self.on_key_press)
        self.root.bind("<Configure>", self.on_root_configure, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_root_configure(self, event):
        if event.widget is not self.root:
            return
        if not self._initializing:
            self.preferences.set("UI", "window_geometry", self.root.geometry())
            from ui_scale import scale
            self.preferences.set("UI", "window_dpi", round(96*scale()))
        content_wrap = max(px(320), event.width - px(56))
        self.routing_label.configure(wraplength=content_wrap)
        self.hint_label.configure(wraplength=content_wrap)
        self.error_label.configure(wraplength=content_wrap)
        self.empty_help_label.configure(wraplength=min(px(460), max(px(300), event.width - px(80))))
        transcript_wrap = max(px(280), event.width - px(56))
        for label in tuple(self.transcript_text_labels):
            try:
                label.configure(wraplength=transcript_wrap)
                refresh_language_text(label)
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

    def apply_language_pair(self):
        from app_config import conversation_for_pair
        source = self.language_entry_by_name(self.listen_source_var.get())[2]
        target = self.language_entry_by_name(self.listen_target_var.get())[2]
        variety = self.variety_var.get()
        if not variety or variety.split("-")[0] not in {catalog_language(source).base_code,catalog_language(target).base_code}:
            self.variety_var.set(pair_default_variety(source,target))
        pair = conversation_for_pair(self.language_entry_by_name(self.listen_source_var.get())[2],
            self.language_entry_by_name(self.listen_target_var.get())[2], self.english_passthrough_var.get(),
            previous=self.current_conversation())
        self.conversation_other_var.set(self.language_name_for_iso(pair.other_language))
        self.my_language_var.set(self.language_name_for_iso(pair.my_language))
        self.audience_language_var.set(self.language_name_for_iso(pair.audience_language))
        self.one_way_var.set(pair.one_way)
        self.update_conversation_controls()
        if hasattr(self, "engine_default_vars"):
            from engine_ui import restore_scope, refresh_measurements
            restore_scope(self)
            refresh_measurements(self)

    def current_conversation(self):
        other = self.language_entry_by_name(self.conversation_other_var.get())[2]
        my_language = self.language_entry_by_name(self.my_language_var.get())[2]
        audience = self.language_entry_by_name(self.audience_language_var.get())[2]
        return ConversationConfig(
            other_language=other, my_language=my_language, audience_language=audience,
            show_both=self.both_languages_var.get(), keep_english_terms=self.keep_english_var.get(),
            same_language_speech={"Pass my voice through": "passthrough", "Read it with the voice": "voice",
                                  "Mute": "mute"}.get(self.same_language_speech_var.get(), "passthrough"),
            one_way=self.one_way_var.get())

    def update_conversation_controls(self, persist=True):
        all_names = [name for name, _, _ in LANGUAGES]
        other = self.conversation_other_var.get()
        if other == "English":
            other = "Arabic"
            self.conversation_other_var.set(other)
        pair = ["English", other]
        if self.my_language_var.get() not in pair:
            self.my_language_var.set("English")
        if self.audience_language_var.get() not in pair:
            self.audience_language_var.set(other)
        one_way = self.one_way_var.get()
        for combo, variable in ((self.listen_source_combo, self.listen_source_var),
                                (self.speak_source_combo, self.speak_source_var)):
            combo.configure(textvariable=variable if one_way or combo is self.listen_source_combo else self.conversation_other_var,
                            values=all_names if one_way or combo is self.listen_source_combo else [x for x in all_names if x != "English"])
        self.listen_target_combo.configure(textvariable=self.listen_target_var, values=all_names)
        self.speak_target_combo.configure(textvariable=self.speak_target_var if one_way else self.audience_language_var,
                                          values=all_names if one_way else pair)
        for label in (self.listen_source_label, self.speak_source_label):
            label.configure(text="From" if label is self.listen_source_label or one_way else "English +")
        self.listen_target_label.configure(text="To")
        self.speak_target_label.configure(text="To" if one_way else "Audience")
        for combo in getattr(self, "conversation_settings_combos", ()):
            if combo.winfo_exists():
                combo.configure(values=pair)
        speech_label = getattr(self, "speech_routing_settings_label", None)
        if speech_label is not None and speech_label.winfo_exists():
            speech_label.configure(text=f"When I speak {self.audience_language_var.get()}")
        advanced = getattr(self, "advanced_language_frame", None)
        if advanced is not None and advanced.winfo_exists():
            advanced.pack(fill="x") if one_way else advanced.pack_forget()
        if persist:
            self.persist_settings()

        voice_variable = self.speak_target_var if one_way else self.audience_language_var
        voice_language = self.language_entry_by_name(voice_variable.get())[2]
        if getattr(self, "_voice_language", None) != voice_language:
            self.refresh_voices()

    def change_quality_preset(self):
        self.whisper_var.set({"Fast": "openai/whisper-small", "Balanced": "openai/whisper-small",
                              "Best": "openai/whisper-large-v3-turbo"}[self.quality_var.get()])
        self.persist_settings()

    def open_terms(self):
        from quality_settings import open_terms_editor
        try:
            open_terms_editor(self, COLORS, center_window)
        except Exception as exc:
            self.show_error(f"Could not open Terms: {exc}")

    def open_arabic_model_setup(self):
        from quality_settings import open_cohere_setup
        open_cohere_setup(self, COLORS, center_window)

    def open_translation_model_setup(self):
        from quality_settings import open_translategemma_setup
        open_translategemma_setup(self, COLORS, center_window)

    def open_speed_check(self, first_run=False):
        if self.transcriber is not None or self.model_setup_busy:
            self.show_hint("Finish the current session or model setup first.")
            return
        from check_ui import open_check
        open_check(self, COLORS, center_window, first_run=first_run)

    def change_engine_profile(self):
        self.persist_settings()

    def open_cloud_setup(self):
        self.open_settings()
        self.engine_choice_var.set("cloud")
        self.settings_shell.show("Engine")
        self.refresh_cloud_connection()
        self.cloud_key_entry.focus_set()

    def open_provider_settings(self):
        from provider_settings import open_provider_settings
        return open_provider_settings(self, COLORS, center_window)

    def change_offline_mode(self):
        self.preferences.set("NETWORK", "block_all", self.offline_only_var.get())
        self.configure_offline_env()
        self.persist_settings()
        if self.offline_only_var.get():
            if getattr(self, "download_manager", None):
                self.download_manager.block_network()
            if getattr(self, "reply_controller", None):
                self.reply_controller.generation += 1
                self.reply_controller.request_stop.set()
                self.reply_controller.stop_speaking()
            # Stop the active transport immediately. A new local session can
            # then start using the saved audio source and language choices.
            if self.transcriber is not None or self.model_setup_busy:
                self.stop()
        if getattr(self, "session_controller", None):
            self.session_controller.refresh()

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
        self._restoring_devices = True
        try:
            self._refresh_devices(show_error=show_error)
        finally:
            self._restoring_devices = False

    def _refresh_devices(self, show_error=False):
        current_listen = self.selected_listen_choice()
        current_is_app = current_listen is not None and getattr(current_listen.raw, "is_process_loopback", False)
        if self.listen_source_type_var.get() == "App audio":
            listen_name = current_listen.name if current_is_app else ""
        else:
            listen_name = (current_listen.name if current_listen and not current_is_app else
                self.preferences.get("CAPTURE", "device_name", "") or load_device_config(CONFIG_FILE))
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
        if self.listen_source_type_var.get() == "App audio":
            from meeting_app import preferred_app, resolve_default_app
            preferred = preferred_app(self)
            from device_utils import InputDeviceChoice
            from engines.process_audio import ProcessSource, active_sources, supported
            if supported():
                try:
                    sources = active_sources()
                    self.listen_choices = [InputDeviceChoice(source.name, source, True, False) for source in sources]
                    matching = (next((s for s in sources if s.exclude), None) if preferred == "*" else resolve_default_app(preferred, sources))
                    previous = current_listen.raw if current_is_app else None
                    if matching is not None:
                        listen_name = matching.name
                    elif isinstance(previous, ProcessSource):
                        matching = next((source for source in sources if (source.pid, source.birth) == (previous.pid, previous.birth)), None)
                        if matching:
                            listen_name = matching.name
                        else:
                            # A silent/closed app must never broaden selection
                            # to All apps during the automatic refresh.
                            retained = InputDeviceChoice(f"{previous.name} — not playing", previous, True, False)
                            self.listen_choices.insert(0, retained)
                            listen_name = retained.name
                    self.app_audio_hint.configure(text="Captures this app and its children. Browser selection includes all its audible tabs.")
                except Exception:
                    self.listen_choices = []
                    self.app_audio_hint.configure(text="App list unavailable. Refresh or choose Device.")
            else:
                self.listen_choices = []
                self.app_audio_hint.configure(text="App audio needs 64-bit Windows build 20348+; use Device here.")
            self.app_audio_hint.grid(row=1, column=0, columnspan=5, sticky="ew", pady=px((6,0)))
        else:
            self.app_audio_hint.configure(text="")
            self.app_audio_hint.grid_remove()
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
        if self.listen_source_type_var.get() == "App audio" and preferred not in {"", "*"} and not any(
                getattr(c.raw,"executable","").casefold() == preferred.casefold() for c in self.listen_choices):
            self.listen_combo.set(preferred + " · waiting for audio")
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
        self.select_virtual_mic_output()
        self.update_routing_banner()

    def select_virtual_mic_output(self):
        if self.mode_var.get() != "speak" or not getattr(self, "_auto_select_speak_output", False):
            return
        from engines.virtual_mic import cable_output
        output = cable_output(self.output_choices)
        if output is not None:
            self.select_combo_by_name(self.speak_output_combo, self.output_choices, output.name)

    def speak_output_selected(self, _event=None):
        self._auto_select_speak_output = False
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
        if self.transcriber is None and not self.model_setup_busy:
            self.refresh_devices(show_error=False)
        self.root.after(3000, self.auto_refresh_devices)

    def manual_refresh_devices(self):
        if self.transcriber is not None or self.model_setup_busy:
            return
        if self.preview_mode:
            self.refresh_devices()
            return
        # Reinitializing PortAudio can block inside a Windows device driver.
        # Never do that on Tk's thread or every three seconds during idle.
        self.model_setup_busy = True
        self.lock_controls(True)
        self.update_action_button(loading=True)
        self.set_status("Refreshing devices")
        def run():
            query_output_devices(refresh=True)
            def done():
                self.model_setup_busy = False
                self.refresh_devices()
                self.lock_controls(False)
                self.update_action_button()
                self.set_status("Ready")
            if not self.is_quitting:
                try:
                    self.post_ui( done)
                except (RuntimeError, tk.TclError):
                    pass
        threading.Thread(target=run, daemon=True, name="Translito device refresh").start()

    def set_mode(self, mode, force=False):
        if self.model_setup_busy or (self.transcriber is not None and not force):
            return
        mode = mode if mode in {"listen", "speak"} else "listen"
        if mode == "speak" and (force or self.mode_var.get() != "speak"):
            self._auto_select_speak_output = True
        self.mode_var.set(mode)
        self.listen_mode_button.configure(
            style="SegmentActive.TButton" if mode == "listen" else "SegmentInactive.TButton"
        )
        self.speak_mode_button.configure(
            style="SegmentActive.TButton" if mode == "speak" else "SegmentInactive.TButton"
        )
        if mode == "speak":
            self.select_virtual_mic_output()
            self.listen_frame.grid_remove()
            self.speak_frame.grid(row=0, column=0, sticky="ew")
        else:
            self.speak_frame.grid_remove()
            self.listen_frame.grid(row=0, column=0, sticky="ew")
            self.routing_banner.grid_remove()
        self.update_routing_banner()
        self.persist_settings()

    def show_virtual_mic_setup(self):
        self.virtual_mic_setup.force_visible = True
        self.virtual_mic_setup.update()

    def update_routing_banner(self):
        self.virtual_mic_setup.update()

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
        variable = self.speak_target_var if self.one_way_var.get() else self.audience_language_var
        _name, _bcp47, target_iso = self.language_entry_by_name(variable.get())
        if getattr(self, "_voice_loading", False) and getattr(self, "_voice_language", None) == target_iso:
            return
        self._voice_language, self._voice_loading = target_iso, True
        self._voice_generation = getattr(self, "_voice_generation", 0) + 1
        generation = self._voice_generation
        def load():
            voices = self.synthesizer.available_voices(target_iso)
            try:
                self.post_ui(lambda: self._apply_voices(voices, target_iso, generation))
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=load, daemon=True).start()

    def _apply_voices(self, voices, target_iso=None, generation=None):
        if generation is not None and generation != self._voice_generation:
            return
        self._voice_loading = False
        from speech_output import windows_voice_hint
        variable = self.speak_target_var if self.one_way_var.get() else self.audience_language_var
        current = self.language_entry_by_name(variable.get())[2]
        if target_iso is not None and target_iso != current:
            return
        self.voice_hint_var.set(windows_voice_hint(current, voices))
        if hasattr(self, "voice_guidance") and self.voice_guidance.winfo_exists():
            if self.voice_hint_var.get():
                self.voice_guidance.pack(fill="x", before=self.voice_settings_monitor)
            else:
                self.voice_guidance.pack_forget()
        if hasattr(self, "voice_settings_combo") and self.voice_settings_combo.winfo_exists():
            self.voice_settings_combo["values"] = voices
        if self.voice_var.get() not in voices:
            restoring = getattr(self, "_restoring_devices", False)
            self._restoring_devices = True
            try:
                self.voice_var.set("Automatic")
            finally:
                self._restoring_devices = restoring

    def update_capture_switch(self):
        for kind, button in self.capture_kind_buttons.items():
            button.configure(style="SegmentActive.TButton" if self.listen_source_type_var.get() == kind else "SegmentInactive.TButton")

    def select_capture_source(self, kind=None):
        if self.transcriber is not None or self.model_setup_busy:
            return
        from meeting_app import cancel_wait
        if self._capture_source_type == "Device":
            self.persist_current_listen_device(kind="Device")
        cancel_wait(self)
        self.meeting_source = None
        self._capture_source_type = kind or self.listen_source_type_var.get()
        self.listen_source_type_var.set(self._capture_source_type)
        self.refresh_devices()
        self.set_status("Ready")

    def persist_current_listen_device(self, kind=None):
        if self._initializing:
            return
        choice = self.selected_listen_choice()
        if not choice:
            return
        kind = kind or self.listen_source_type_var.get()
        is_app = getattr(choice.raw,"is_process_loopback",False)
        if kind == "App audio" and is_app and self.listen_combo.current() >= 0:
            from meeting_app import executable_name
            self.preferences.set("CAPTURE", "app_executable", "*" if choice.raw.exclude else executable_name(choice.raw))
            self.meeting_source = choice.raw
        elif kind == "Device" and not is_app:
            self.preferences.set("CAPTURE", "device_name", choice.name)
            if not self.preview_mode:
                save_device_config(choice.name, CONFIG_FILE)

    def persist_settings(self):
        if self.preview_mode or self._initializing:
            return
        from dataclasses import asdict
        # Control traces already save their own canonical keys. Update only the
        # derived conversation contract as one transaction.
        self.preferences.store.update({("CONVERSATION", key): str(int(value)) if isinstance(value, bool) else str(value)
            for key, value in asdict(self.current_conversation()).items()})

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
        os.environ["OFFLINE_ONLY"] = "1" if self.offline_only_var.get() else "0"

    def current_model_request(self):
        controller = getattr(self, "session_controller", None)
        if controller:
            controller.refresh()
            plan = controller.plan
            return dict(mode=plan.mode, src_bcp47=next(bcp for _, bcp, iso in LANGUAGES if iso == plan.pair[0]),
                src_iso=plan.pair[0], tgt_iso=plan.pair[1], whisper_model=plan.whisper_model,
                variety=self.variety_var.get(), translation_model=plan.translation_model,
                cloud_translation=plan.cloud_translation, conversation=self.current_conversation(),
                session_plan=plan, engine_settings=controller.settings())
        mode = self.mode_var.get()
        conversation = self.current_conversation()
        if not conversation.one_way:
            tgt_iso = conversation.my_language if mode == "listen" else conversation.audience_language
            src_iso = conversation.other_language if tgt_iso == "en" else "en"
            src_bcp47 = next(bcp for _name, bcp, iso in LANGUAGES if iso == src_iso)
        elif mode == "speak":
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
        settings = load_engine_settings(self.preferences.path)
        defaults = settings.resolve(src_iso, tgt_iso)
        whisper_model = self.whisper_var.get().strip() or "openai/whisper-small"
        if defaults["default_asr_provider"] == "local":
            whisper_model = defaults["default_asr_model"] or whisper_model
        cloud_available = (not self.offline_only_var.get() and self.engine_profile_var.get() != "Offline (private)" and
            any(p.enabled and p.tested_signature and (settings.engine_choice != "free" or p.account_kind != "paid")
                for name,p in settings.providers.items() if name in {"azure","deepl","google","gemini","gemini-live","soniox","elevenlabs","speechmatics"}))
        native_cloud = (settings.engine_choice == "cloud" and (defaults["default_asr_provider"] or "soniox") == "soniox"
            and settings.monthly_cap > 0 and settings.provider("soniox").enabled and settings.provider("soniox").monthly_cap > 0 and bool(settings.provider("soniox").tested_signature)
            and not self.offline_only_var.get())
        text_cloud = cloud_available and any(p.enabled and p.tested_signature and
            (p.account_kind != "paid" or (settings.monthly_cap > 0 and p.monthly_cap > 0)) for name,p in settings.providers.items()
            if name in {"azure", "deepl", "google", "gemini"})
        translation_model = (f"cloud:{src_iso}:{tgt_iso}" if native_cloud or text_cloud else
                             translation_model_for(src_iso, tgt_iso, cloud_available=cloud_available))
        if defaults["default_mt_provider"] == "local" and defaults["default_mt_model"] == "opus" and not native_cloud:
            translation_model = resolve_local_mt(src_iso,tgt_iso,offline=True).model_id
        return {
            "mode": mode,
            "src_bcp47": src_bcp47,
            "src_iso": src_iso,
            "tgt_iso": tgt_iso,
            "whisper_model": whisper_model,
            "variety": self.variety_var.get(),
            "translation_model": translation_model,
            "cloud_translation": native_cloud or text_cloud,
            "conversation": conversation,
        }

    def toggle_capture(self):
        if getattr(self, "model_setup_busy", False) and getattr(self, "session_controller", None):
            self.stop()
            return
        if getattr(self, "_waiting_meeting_app", False):
            self.stop()
            self.set_status("Ready")
            return
        if self.transcriber is None:
            self.start()
        else:
            self.stop()

    def start(self, owner="manual"):
        if getattr(self, "_waiting_meeting_app", False):
            owner = getattr(self, "_waiting_owner", owner)
        controller = getattr(self, "session_controller", None)
        if controller and not self.model_setup_busy and self.transcriber is None:
            if not controller.before_start(interactive=owner == "manual"):
                return "blocked"
        if hasattr(self, "default_app_var") and not self.model_setup_busy:
            from meeting_app import prepare_source
            if not prepare_source(self):
                self._waiting_owner = owner
                if controller:
                    controller.render_action()
                return "pending"
        if self.transcriber is not None:
            return
        if getattr(self, "model_setup_busy", False):
            self.show_hint("Wait for device or model setup to finish before starting a session.")
            return
        try:
            request = self.current_model_request()
        except UnsupportedPairError as exc:
            messagebox.showwarning("Translation engine", str(exc), parent=self.root)
            return
        if request["src_iso"] == request["tgt_iso"]:
            messagebox.showwarning(
                "Language",
                "Source and target languages must be different.",
                parent=self.root,
            )
            return

        self.configure_offline_env()
        self.persist_settings()
        from engines.usage import UsageLedger
        from decimal import Decimal
        try:
            self.session_cost_baseline = sum(Decimal(v["estimated_usd"]) for v in UsageLedger().snapshot()["providers"].values())
        except Exception:
            self.session_cost_baseline = Decimal(0)
        self.hide_banners()
        self.active_fallbacks = {"asr": False, "mt": False}
        self.engine_label.configure(fg=COLORS["secondary"])
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
            if not output_choice or "cable input" not in output_name.lower():
                self.show_virtual_mic_setup()
                self.show_hint("Choose CABLE Input under Speak to, then test the virtual microphone before starting.")
                return
        else:
            listen_choice = self.selected_listen_choice()
            if listen_choice is None:
                messagebox.showwarning(
                    "Device", "Select an audio device first.", parent=self.root
                )
                return
            selected_device = listen_choice.raw
            output_name = ""
            if self.listen_source_type_var.get() == "Device":
                save_device_config(listen_choice.name, CONFIG_FILE)
            else:
                try:
                    selected_device.validate()
                except Exception as exc:
                    self.show_error(str(exc))
                    return

        from engines.model_files import ready_whisper
        fallback = request["whisper_model"] if controller else ready_whisper(request["whisper_model"])
        if fallback is None:
            self.download_missing_whisper()
            return
        if fallback != request["whisper_model"]:
            request["whisper_model"] = fallback
            self.refresh_model_hint()
        if not request.get("cloud_translation") and not request["translation_model"].startswith(("translategemma:", "identity:")):
            from engines.model_files import missing_translations
            needed = missing_translations(request["src_iso"], request["tgt_iso"])
            if needed:
                for spec in needed:
                    self.download_missing_whisper(spec)
                self.show_hint("Lite translation is downloading. It will be used from your next session.")
                return
        self.model_setup_busy = True
        self.lock_controls(True)
        self.set_status("Testing virtual microphone" if request["mode"] == "speak" else "Loading models")
        self.update_action_button(running=False, loading=True)

        session_options = dict(speech_voice=self.voice_var.get(), monitor_spoken_audio=self.monitor_var.get(),
            chunk_duration=self.chunk_duration_var.get(), transcript_folder=self.transcript_folder_var.get(),
            asr_preset=self.quality_var.get().lower(),
            engine_settings=load_engine_settings(self.preferences.path) if hasattr(self, "preferences") else None)
        token = controller.begin(owner) if controller else None
        if controller:
            session_options.update(engine_settings=request["engine_settings"], session_plan=request["session_plan"])

        def failed(error):
            if not controller or controller.accepts(token):
                self.start_failed(error)

        def session_event(kind, payload):
            if not controller or controller.allows_event(token):
                self.on_event(kind, payload, token=token)

        def run_start():
            try:
                if request["mode"] == "speak":
                    from engines.virtual_mic import self_test
                    result = self_test(output_choice)
                    self.post_ui( lambda: self.virtual_mic_setup.test_result(output_choice, result))
                    if not result.passed:
                        self.post_ui( lambda: failed(RuntimeError(result.message)))
                        return
                    self.post_ui( lambda: self.set_status("Loading models"))
                transcriber = ArabicAudioTranscriber(
                    selected_device=selected_device,
                    on_event=session_event if controller else self.on_event,
                    interactive=False,
                    asr_language=request["src_bcp47"],
                    translation_model=request["translation_model"],
                    mode=request["mode"],
                    target_language=request["tgt_iso"],
                    speech_output_device_name=output_name,
                    mic_noise_gate=mic_noise_gate,
                    conversation=request["conversation"],
                    **session_options,
                    variety=request.get("variety", ""),
                    whisper_model=request.get("whisper_model"),
                )
            except Exception as exc:
                self.post_ui( lambda exc=exc: failed(exc))
                return

            def finish_start():
                if controller and not controller.accepts(token):
                    transcriber.stop_background()
                    return
                self.model_setup_busy = False
                self.transcriber = transcriber
                if controller:
                    controller.started(token, request["session_plan"])
                self.update_routing_banner()
                self.set_status("Listening")
                self.phase_var.set("")
                self.progress.stop()
                self.progress.grid_remove()
                self.phase_label.grid_remove()
                self.level_frame.grid(row=1,column=5)
                self.update_action_button(running=True)
                transcriber.start_background(enable_keyboard_shortcuts=False)

            self.post_ui( finish_start)

        threading.Thread(target=run_start, daemon=True).start()
        return "pending"

    def start_failed(self, exc):
        if getattr(self, "session_controller", None):
            self.session_controller.cancel()
        self.model_setup_busy = False
        self.lock_controls(False)
        self.set_status("Error")
        self.update_action_button(running=False)
        from engines.model_files import ModelNotReady
        if isinstance(exc, ModelNotReady):
            from engines.model_files import model_hint
            message, action = model_hint(exc.spec, exc.status)
            self.show_hint(message)
            self.hint_action.configure(text=action, command=lambda: self.download_missing_whisper(exc.spec))
            self.hint_action.pack(side="right")
            self.set_status("Ready")
        else:
            self.show_error(str(exc))
        self.update_routing_banner()

    def stop(self, after=None):
        if getattr(self, "_stopping", False):
            if callable(after):
                self.root.after(100, lambda: self.stop(after=after))
            return
        controller = getattr(self, "session_controller", None)
        if controller:
            controller.cancel()
        if hasattr(self, "reply_controller"):
            self.reply_controller.stop_speaking()
        self._waiting_meeting_app = False
        self._waiting_owner = None
        if getattr(self, "_meeting_timer", None) is not None:
            self.root.after_cancel(self._meeting_timer)
            self._meeting_timer = None
        transcriber = self.transcriber
        if transcriber is None:
            if controller:
                self.model_setup_busy = False
                self.lock_controls(False)
                self.finish_model_progress()
                self.set_status("Ready")
                controller.refresh()
            if callable(after):
                after()
            return
        self._stopping = True
        self.set_status("Stopping")
        self.update_action_button(running=True, loading=True)
        transcriber.stop_background()

        def finalize():
            transcriber.join_background()
            save_error = ""
            try:
                saved_path = transcriber.save_transcript()
            except (OSError, ValueError) as error:
                saved_path, save_error = None, str(error)

            def done():
                self.last_transcriber = transcriber
                self.last_saved_path = saved_path or transcriber.last_saved_path
                self.transcriber = None
                self._stopping = False
                if controller:
                    controller.active_owner, controller.active_plan = None, None
                    controller.active_token = None
                    controller.actual_engines, controller.failure = {}, ""
                self.lock_controls(False)
                self.set_status("Ready")
                self.level_frame.grid_remove()
                self.update_level(0)
                self.lag_var.set("")
                self.update_action_button(running=False)
                if save_error:
                    self.show_hint("Transcript kept in memory. Save it again after checking the folder: " + save_error)
                if callable(after):
                    after()

            self.post_ui( done)

        threading.Thread(target=finalize, daemon=True).start()

    def hotkey_toggle(self):
        if self.transcriber is None:
            self.set_mode(self.mode_var.get(), force=True)
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
            *self.capture_kind_buttons.values(),
        ):
            widget.configure(state=normal_state)
        self._set_settings_controls_state(True)
        self.update_routing_banner()

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
        if getattr(self, "session_controller", None):
            self.session_controller.refresh()
            return
        button = self.speak_action_button if self.mode_var.get() == "speak" else self.listen_action_button
        other = self.listen_action_button if button is self.speak_action_button else self.speak_action_button
        other.configure(state="disabled" if running or loading else "normal")
        if loading:
            button.configure(text="Please wait…", style="Mac.TButton", state="disabled")
        elif running:
            button.configure(text="■  Stop", style="Stop.TButton", state="normal")
        else:
            from engines.model_files import ready_whisper
            if not self.preview_mode and ready_whisper(self.whisper_var.get()) is None:
                button.configure(text="Download Whisper Small (484 MB) to start", style="Primary.TButton", state="normal")
                return
            if not self.preview_mode:
                try:
                    request = self.current_model_request()
                    if not request.get("cloud_translation") and not request["translation_model"].startswith(("translategemma:", "identity:")):
                        from engines.model_files import missing_translations
                        if missing_translations(request["src_iso"], request["tgt_iso"]):
                            button.configure(text="Download Lite translation to start", style="Primary.TButton", state="normal")
                            return
                except UnsupportedPairError:
                    pass
            symbol = "●" if self.mode_var.get() == "speak" else "▶"
            button.configure(text=f"{symbol}  Start", style="Primary.TButton", state="normal")

    # ------------------------------------------------------------------
    # Status, transcript, and model progress

    def on_event(self, event_type, payload, *, token=None):
        def handle():
            if token is not None and not self.session_controller.allows_event(token):
                return
            if event_type == "status":
                self.set_status(self.pretty_status(str(payload)))
            elif event_type == "budget":
                self.set_status("Budget reached")
                self.show_hint("Monthly budget reached. " + ("Continuing on this PC." if (payload or {}).get("action") == "local" else "Stopped."))
                if (payload or {}).get("action") == "stop" and self.transcriber is not None:
                    self.stop()
            elif event_type == "setup_required":
                if self.transcriber is not None:
                    self.stop()
                self.show_hint((payload or {}).get("message", "Finish setup before continuing."))
            elif event_type == "delay":
                delay = (payload or {}).get("delay_median_s")
                self.delay_var.set(f"Delay {delay:.1f} s" if delay is not None else "Delay —")
            elif event_type == "model_progress":
                self.handle_model_progress(payload or {})
            elif event_type == "hint":
                self.show_hint(str(payload))
            elif event_type == "engine_fallback":
                from engine_ui import refresh_engine_status
                self._engine_fallback_reason = str(payload)
                if getattr(self, "session_controller", None) and str(payload) == "key rejected":
                    plan = self.session_controller.active_plan
                    if plan:
                        self.session_controller.credentials[plan.asr] = False
                status = refresh_engine_status(self, str(payload))
                self.show_hint(status.text)
                tk.Label(self.transcript_scroll.content, text=status.text, bg=COLORS["bg"], fg=COLORS["orange"],
                         wraplength=px(600), justify="left").pack(fill="x", pady=px(8))
            elif event_type == "gap":
                seconds = round((payload or {}).get("seconds", 0))
                tk.Label(self.transcript_scroll.content, text=f"{seconds//60} min {seconds%60} s · nothing sent",
                         bg=COLORS["bg"], fg=COLORS["tertiary"], font=("Segoe UI", 8), pady=px(12)).pack(fill="x")
            elif event_type == "error":
                self.show_error(str(payload))
                self.set_status("Error")
            elif event_type == "transcript":
                self.schedule_controller.scheduler.notify_speech()
                self.append_transcript_card(payload or {})
            elif event_type == "transcript_update":
                self.update_transcript_card(payload or {})
            elif event_type == "level":
                self.update_level(float((payload or {}).get("peak", 0)))
            elif event_type == "lag":
                seconds = float((payload or {}).get("seconds", 0))
                self.lag_var.set(f"Behind by {seconds:.0f}s" if seconds >= 1 else "")
            elif event_type == "engine":
                if getattr(self, "session_controller", None):
                    self.session_controller.actual_engines.update({k: payload[k] for k in ("asr", "mt") if payload.get(k)})
                    if payload.get("fallback") is False:
                        self.session_controller.failure = ""
                for key in ("asr", "mt"):
                    if (payload or {}).get(key):
                        self.active_engines[key] = payload[key]
                if self.engine_choice_var.get() == "cloud":
                    from engine_ui import refresh_engine_status
                    if (payload or {}).get("fallback") is False:
                        self._engine_fallback_reason = ""
                    refresh_engine_status(self, getattr(self, "_engine_fallback_reason", ""))
                else:
                    self.engine_var.set(f"Engine  {self.active_engines['asr']} / {self.active_engines['mt']}")
                if "fallback" in (payload or {}):
                    stages = [payload["stage"]] if payload.get("stage") in {"asr", "mt"} else [
                        key for key in ("asr", "mt") if payload.get(key)]
                    for stage in stages:
                        self.active_fallbacks[stage] = payload["fallback"]
                    self.engine_label.configure(fg=COLORS["orange"] if any(self.active_fallbacks.values()) else COLORS["secondary"])

        self.post_ui( handle)

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
        self.progress.grid(row=0, column=2, padx=px((12, 8)), sticky="w")
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
        self.level_canvas.coords("level", 0, 0, px(110) * peak, px(8))
        self.peak_var.set(f"peak {peak:.4f}")

    def show_hint(self, message):
        self.hint_action.pack_forget()
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
        if hasattr(self, "subtitle_controller"):
            self.subtitle_controller.accept(entry)
        if hasattr(self, "reply_controller"):
            self.reply_controller.accept(entry)
        if entry.get("id") in self.transcript_targets:
            self.update_transcript_card(entry)
            return
        self.transcript_entries.append(entry)
        card_bg = COLORS["bg"]
        card = tk.Frame(
            self.transcript_scroll.content,
            bg=card_bg,
            highlightbackground=COLORS["separator"],
            highlightthickness=px(0),
            padx=px(16),
            pady=px(12),
        )
        card.pack(fill="x")
        tk.Frame(self.transcript_scroll.content, bg=COLORS["separator"], height=px(1)).pack(fill="x", padx=px(16))

        header = tk.Frame(card, bg=card_bg)
        header.pack(fill="x", pady=px((0, 4)))
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
        tk.Label(header, text=entry.get("language_tag", entry.get("source_language", "")).upper(),
                 bg=COLORS["field"], fg=COLORS["blue"], padx=px(5),
                 font=("Segoe UI Semibold", 8)).pack(side="left", padx=px((8, 0)))
        source_info = self.current_source_info(entry)
        if entry.get("delay_s") is not None:
            source_info += f" · {entry['delay_s']:.1f} s"

        meta_label = tk.Label(
            header,
            text=source_info,
            bg=card_bg,
            fg=COLORS["tertiary"],
            font=("Segoe UI", 8),
        )
        meta_label.pack(side="left", padx=px((9, 0)))
        self.transcript_meta[entry.get("id")] = meta_label

        source_text = entry.get("source_text", entry.get("arabic_text", ""))
        translated_text = entry.get("translated_text", entry.get("english_text", ""))
        self.latest_translation = translated_text or source_text
        source_language = entry.get("source_language", "")
        target_language = entry.get("target_language", "")
        tag = entry.get("language_tag", source_language)
        source_rtl = dominant_rtl(source_text) or (source_language in RTL_LANGUAGES and tag != "en")
        source_anchor = "e" if source_rtl and not entry.get("pass_through") else "w"
        target_anchor = "e" if dominant_rtl(translated_text) else "w"
        source_label = tk.Label(
            card,
            text=display_text(source_text),
            bg=card_bg,
            fg=COLORS["text"] if entry.get("pass_through") else COLORS["secondary"],
            anchor=source_anchor,
            justify="right" if source_anchor == "e" else "left",
            wraplength=px(800),
            font=("Segoe UI", 10),
        )
        source_label.pack(fill="x")
        configure_language_text(source_label, source_text, source_language, 10)
        self.transcript_text_labels.append(source_label)
        if translated_text or entry.get("id"):
            translated_label = tk.Label(
                card,
                text=self.transcript_target_text(entry),
                bg=card_bg,
                fg=COLORS["tertiary"] if entry.get("translation_pending") else COLORS["text"],
                anchor=target_anchor,
                justify="right" if target_anchor == "e" else "left",
                wraplength=px(800),
                font=("Segoe UI", 10),
            )
            translated_label.pack(fill="x", before=source_label, pady=px((0, 5)))
            configure_language_text(translated_label, self.transcript_target_text(entry), target_language, 10, displayed=True)
            if not self.transcript_target_text(entry):
                translated_label.pack_forget()
            self.transcript_text_labels.append(translated_label)
            if entry.get("id"):
                self.transcript_targets[entry["id"]] = (entry, translated_label, source_label)
        self.update_transcript_state()
        self.refresh_tray_menu()
        self.root.after(10, lambda: self.transcript_scroll.canvas.yview_moveto(1.0))

    @staticmethod
    def transcript_target_text(entry):
        if entry.get("translation_pending"):
            return display_text(entry.get("translated_text") or "Hearing…")
        if entry.get("translation_cancelled"):
            return "Translation stopped."
        if entry.get("translation_error"):
            return f"Translation failed: {entry['translation_error']}"
        if entry.get("pass_through") and not entry.get("secondary_translation"):
            return ""
        return display_text(entry.get("translated_text", entry.get("english_text", "")))

    def update_transcript_card(self, entry):
        if hasattr(self, "subtitle_controller"):
            self.subtitle_controller.accept(entry)
        if hasattr(self, "reply_controller"):
            self.reply_controller.accept(entry)
        target = self.transcript_targets.get(entry.get("id"))
        if target is None:
            return
        stored_entry, label, source_label = target
        stored_entry.update(entry)
        meta = self.transcript_meta.get(entry.get("id"))
        if meta is not None:
            meta.configure(text=self.current_source_info(stored_entry) + (f" · {entry['delay_s']:.1f} s" if entry.get("delay_s") is not None else ""))

        label.configure(text=self.transcript_target_text(stored_entry), fg=COLORS["tertiary"] if stored_entry.get("translation_pending") else COLORS["text"])
        source = stored_entry.get("source_text", "")
        source_rtl = dominant_rtl(source) or (stored_entry.get("source_language") in RTL_LANGUAGES
                     and stored_entry.get("language_tag") != "en")
        source_label.configure(text=display_text(source), anchor="e" if source_rtl and not stored_entry.get("pass_through") else "w",
                               justify="right" if source_rtl and not stored_entry.get("pass_through") else "left")
        configure_language_text(source_label, source, stored_entry.get("source_language"), 10)
        configure_language_text(label, self.transcript_target_text(stored_entry), stored_entry.get("target_language"), 10, displayed=True)
        translated = stored_entry.get("translated_text", "")
        label.configure(anchor="e" if dominant_rtl(translated) else "w",
                         justify="right" if dominant_rtl(translated) else "left")
        if self.transcript_target_text(stored_entry):
            label.pack(fill="x", before=source_label, pady=px((0, 5)))
        else:
            label.pack_forget()
        self.latest_translation = stored_entry.get("translated_text") or stored_entry.get("source_text", "")
        self.refresh_tray_menu()

    def current_source_info(self, entry):
        if entry.get("not_sent"):
            return "shown as spoken, not sent"
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
            self.empty_state.grid(row=0, column=0, sticky="new", padx=px(24), pady=px((56, 0)))

    def clear_transcript(self):
        self.transcript_entries.clear()
        self.transcript_targets.clear()
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
        try:
            saved = transcriber.save_transcript()
        except (OSError, ValueError) as error:
            self.show_hint("Transcript kept in memory. Check the folder and try saving again: " + str(error))
            return
        if saved:
            self.last_saved_path = saved
            self.show_hint(f"Transcript saved to {saved}")

    def reveal_transcripts(self):
        folder = Path(self.transcript_folder_var.get()).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.show_hint("The transcript folder is unavailable: " + str(error))
            return
        if os.name != "nt":
            return
        saved = Path(self.last_saved_path) if self.last_saved_path else None
        if saved and saved.exists():
            subprocess.Popen(["explorer", "/select,", str(saved)])
        else:
            os.startfile(folder)

    def download_models(self):
        from model_library_ui import ModelManagerWindow
        existing = getattr(self, "model_manager", None)
        if existing is not None and existing.window.winfo_exists():
            parent = dialog_parent(self)
            existing.window.transient(parent)
            center_window(existing.window, parent)
            existing.window.lift()
            existing.selection_changed()
            return
        self.model_manager = ModelManagerWindow(self, COLORS, center_window)

    def preload_current_models(self, force_online=False):
        if getattr(self, "session_controller", None):
            self.session_controller.refresh()
            return
        if self.preview_mode or self.transcriber is not None or self.model_setup_busy:
            return
        try:
            request = self.current_model_request()
        except UnsupportedPairError as exc:
            self.show_hint(str(exc))
            return
        if self.engine_choice_var.get() != "local":
            return
        from engines.model_files import inspect_model, whisper_spec, Ready
        if not isinstance(inspect_model(whisper_spec(request["whisper_model"])), Ready):
            self.refresh_model_hint()
            return
        offline_only = True
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
                self.post_ui( lambda: self.set_status("Ready"))
            except Exception as exc:
                self.post_ui( lambda: self.refresh_model_hint())
                self.post_ui( lambda: self.set_status("Ready"))
            finally:
                self.post_ui( self.finish_model_progress)

        threading.Thread(target=run_preload, daemon=True).start()

    def refresh_model_hint(self):
        if getattr(self, "session_controller", None):
            self.session_controller.refresh()
            return
        from engines.model_files import whisper_spec, inspect_model, ready_whisper, Ready, model_hint
        spec = whisper_spec(self.whisper_var.get())
        status = inspect_model(spec)
        if not isinstance(status, Ready):
            fallback = ready_whisper(spec.key)
            message, action = model_hint(spec, status, whisper_spec(fallback).title if fallback else None)
            self.show_hint(message)
            self.hint_action.configure(text=action, command=lambda: self.download_missing_whisper(spec))
            self.hint_action.pack(side="right", padx=px(8))

    def download_missing_whisper(self, spec=None):
        if self.offline_only_var.get():
            self.show_hint("Internet is blocked. Turn off Never connect to the internet to download models.")
            return
        from engines.model_files import whisper_spec
        spec = spec or whisper_spec("openai/whisper-small")
        if hasattr(self, "download_manager"):
            self.download_manager.enqueue_model(spec)
        else:
            self.download_models()

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
        if hasattr(self, "reply_controller"):
            self.reply_controller.render()
        hotkeys = {action: variable.get() for action, variable in self.hotkey_vars.items()}
        save_hotkey_config(CONFIG_FILE, hotkeys)
        self.register_hotkeys()

    def register_hotkeys(self):
        if self.preview_mode:
            return
        hotkeys = {action: variable.get() for action, variable in self.hotkey_vars.items()}
        if self.hotkey_manager.register(hotkeys) is False:
            previous = self.hotkey_manager.last_registered
            if previous:
                for action, combo in previous.items():
                    if action in self.hotkey_vars:
                        self.hotkey_vars[action].set(combo)
                save_hotkey_config(CONFIG_FILE, previous)

    # ------------------------------------------------------------------
    # Windows notification-area counterpart to the macOS MenuBarExtra

    def setup_tray(self):
        try:
            import pystray
            from PIL import Image

            self.tray_images = {state: Image.open(app_resource_path(f"engines/data/tray/{state}-64.png")).convert("RGBA")
                                for state in ("idle", "listening", "paused")}
            image = self.tray_images["idle"]
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
                pystray.MenuItem("Subtitles on screen", lambda _icon, _item: self.post_ui( self.toggle_subtitles),
                                checked=lambda _item: getattr(self, "_tray_subtitles_enabled", False)),
                pystray.MenuItem(
                    lambda _item: "Stop" if self.transcriber is not None else "Start Listening",
                    lambda _icon, _item: self.post_ui( self.tray_primary_action),
                ),
                pystray.MenuItem(
                    "Start Speak Mode",
                    lambda _icon, _item: self.post_ui( self.tray_start_speak),
                    visible=lambda _item: self.transcriber is None,
                ),
                pystray.MenuItem(
                    "Open Translito Window",
                    lambda _icon, _item: self.post_ui( self.show_main_window),
                    default=True,
                ),
                pystray.MenuItem(
                    "Save Transcript",
                    lambda _icon, _item: self.post_ui( self.save_transcript),
                    enabled=lambda _item: bool(self.transcript_entries),
                ),
                pystray.MenuItem(lambda item: getattr(self, "download_status_text", "") or "No downloads running", lambda *args: None, enabled=False),
                pystray.MenuItem("Pause / resume download", lambda *_: self.post_ui(lambda: self.download_control("pause")),
                                enabled=lambda _: getattr(self, "download_current", None) is not None),
                pystray.MenuItem("Cancel download", lambda *_: self.post_ui(lambda: self.download_control("cancel")),
                                enabled=lambda _: getattr(self, "download_current", None) is not None),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Settings…",
                    lambda _icon, _item: self.post_ui( self.show_settings_from_tray),
                ),
                pystray.MenuItem(
                    "Quit",
                    lambda _icon, _item: self.post_ui( self.quit_app),
                ),
            )
            from windows_icons import tray_icon_class
            self.tray_icon = tray_icon_class()("Translito", image, APP_NAME, menu)
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
        if hasattr(self, "subtitles_enabled_var"):
            self._tray_subtitles_enabled = self.subtitles_enabled_var.get()
        if self.tray_icon is not None:
            try:
                state = ("paused" if any(word in self.current_status.lower() for word in ("budget", "paused", "error")) else
                         "listening" if self.transcriber is not None else "idle")
                if hasattr(self.tray_icon, "set_state"):
                    self.tray_icon.set_state(state)
                elif getattr(self, "tray_images", None):
                    self.tray_icon.icon = self.tray_images[state]
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
        center_window(self.root)
        self.root.lift()
        self.root.focus_force()

    def show_settings_from_tray(self):
        self.show_main_window()
        self.open_settings()

    def quit_app(self):
        if self.download_manager.active and not messagebox.askyesno("Download in progress",
                "Quit and resume the download next time?", parent=self.root):
            return
        self.download_manager.close()
        if getattr(self, "session_controller", None):
            self.session_controller.close()
        self.preferences.close()
        self.is_quitting = True
        self.subtitle_controller.close()
        self.reply_controller.close()
        self.virtual_mic_setup.poll_stop.set()
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
    from ui_scale import enable_system_dpi_awareness
    enable_system_dpi_awareness()
    failure_message = dependency_failure_message()
    if failure_message:
        show_startup_error(f"{APP_NAME} startup error", failure_message)
        return

    require_dependencies()
    hide_console_window()
    if sys.platform == "win32":
        import ctypes
        from app_identity import APP_USER_MODEL_ID
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    root = tk.Tk()
    if "--tray" in sys.argv:
        root.withdraw()
    TranslatorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    gui_main()
