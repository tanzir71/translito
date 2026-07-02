import configparser
from contextlib import redirect_stderr, redirect_stdout
import os
import threading
import tkinter as tk
from tkinter import messagebox

from main import (
    ArabicAudioTranscriber,
    CONFIG_FILE,
    dependency_failure_message,
    device_type_label,
    is_desktop_audio_device,
    load_device_config,
    save_device_config,
    require_dependencies,
    sc,
)


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

COLORS = {
    "bg": "#1f1f1f",
    "panel": "#1f1f1f",
    "output": "#101010",
    "field": "#2a2a2a",
    "field_disabled": "#242424",
    "border": "#45464d",
    "line": "#333333",
    "text": "#f2f2f5",
    "muted": "#a5a5ad",
    "subtle": "#72727a",
    "accent": "#0a84ff",
    "accent_active": "#1e90ff",
    "success": "#30d158",
    "warning": "#ffd60a",
    "error": "#ff453a",
}


class TkLogWriter:
    def __init__(self, emit):
        self.emit = emit
        self.buffer = ""

    def write(self, data):
        if not data:
            return 0
        self.buffer += data.replace("\r", "\n")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.strip()
            if line:
                self.emit(line)
        return len(data)

    def flush(self):
        line = self.buffer.strip()
        if line:
            self.emit(line)
        self.buffer = ""


class AppButton(tk.Frame):
    def __init__(self, parent, text, command, bg, fg, border, font_weight="normal", padx=14, pady=7, font_size=13):
        super().__init__(parent, bg=border, highlightthickness=0, bd=0)
        self.command = command
        self.enabled = True
        self.bg_color = bg
        self.fg_color = fg
        self.border_color = border
        self.disabled_bg = COLORS["field_disabled"]
        self.disabled_fg = COLORS["subtle"]
        self.label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            padx=padx,
            pady=pady,
            font=("Helvetica", font_size, font_weight),
            cursor="hand2",
        )
        self.label.pack(fill="both", expand=True, padx=1, pady=1)
        self.bind("<Button-1>", self._click)
        self.label.bind("<Button-1>", self._click)

    def _click(self, _event=None):
        if self.enabled and self.command:
            self.command()

    def set_text(self, text):
        self.label.configure(text=text)

    def set_colors(self, bg=None, fg=None, border=None):
        if bg is not None:
            self.bg_color = bg
        if fg is not None:
            self.fg_color = fg
        if border is not None:
            self.border_color = border
            super().configure(bg=border)
        if self.enabled:
            self.label.configure(bg=self.bg_color, fg=self.fg_color)

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.label.configure(
            bg=(self.bg_color if enabled else self.disabled_bg),
            fg=(self.fg_color if enabled else self.disabled_fg),
            cursor=("hand2" if enabled else "arrow"),
        )


class FlatCombobox(tk.Frame):
    def __init__(self, parent, textvariable, values=None, state="readonly"):
        super().__init__(parent, bg=COLORS["border"], bd=0, highlightthickness=0, height=32)
        self.textvariable = textvariable
        self.values = list(values or [])
        self.state = state
        self._current_index = -1
        self._popup = None
        self.grid_propagate(False)
        self.pack_propagate(False)

        self.field = tk.Frame(self, bg=COLORS["field"], bd=0, highlightthickness=0, cursor="hand2")
        self.field.pack(fill="both", expand=True, padx=1, pady=1)
        self.field.columnconfigure(0, weight=1)

        self.text = tk.Label(
            self.field,
            textvariable=self.textvariable,
            bg=COLORS["field"],
            fg=COLORS["text"],
            anchor="w",
            padx=9,
            font=("Helvetica", 13),
            cursor="hand2",
        )
        self.text.grid(row=0, column=0, sticky="nsew")

        self.arrow = tk.Canvas(self.field, width=28, height=28, bg=COLORS["field"], highlightthickness=0, bd=0, cursor="hand2")
        self.arrow.grid(row=0, column=1, sticky="ns")
        self._draw_arrow()

        for widget in (self, self.field, self.text, self.arrow):
            widget.bind("<Button-1>", self._toggle_popup)

        self.textvariable.trace_add("write", lambda *_: self._sync_index_from_value())
        self.configure(state=state)

    def _draw_arrow(self):
        self.arrow.delete("all")
        color = COLORS["subtle"] if self.state == "disabled" else COLORS["muted"]
        self.arrow.create_line(10, 12, 14, 16, 18, 12, fill=color, width=2, capstyle="round", joinstyle="round")

    def _sync_index_from_value(self):
        value = self.textvariable.get()
        try:
            self._current_index = self.values.index(value)
        except ValueError:
            self._current_index = -1

    def _set_visual_state(self):
        disabled = self.state == "disabled"
        field_bg = COLORS["field_disabled"] if disabled else COLORS["field"]
        border = COLORS["line"] if disabled else COLORS["border"]
        fg = COLORS["subtle"] if disabled else COLORS["text"]
        cursor = "arrow" if disabled else "hand2"

        super().configure(bg=border)
        self.field.configure(bg=field_bg, cursor=cursor)
        self.text.configure(bg=field_bg, fg=fg, cursor=cursor)
        self.arrow.configure(bg=field_bg, cursor=cursor)
        self._draw_arrow()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if "values" in kwargs:
            self.values = list(kwargs.pop("values"))
            self._sync_index_from_value()
        if "state" in kwargs:
            self.state = kwargs.pop("state")
            if self.state == "disabled":
                self._close_popup()
            self._set_visual_state()
        if kwargs:
            return super().configure(**kwargs)
        return None

    config = configure

    def __setitem__(self, key, value):
        if key == "values":
            self.configure(values=value)
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == "values":
            return tuple(self.values)
        return super().__getitem__(key)

    def current(self, index=None):
        if index is None:
            return self._current_index
        if 0 <= index < len(self.values):
            self._current_index = index
            self.textvariable.set(self.values[index])
        else:
            self._current_index = -1
            self.textvariable.set("")

    def get(self):
        return self.textvariable.get()

    def _toggle_popup(self, _event=None):
        if self.state == "disabled" or not self.values:
            return "break"
        if self._popup is not None:
            self._close_popup()
        else:
            self._open_popup()
        return "break"

    def _open_popup(self):
        self.update_idletasks()
        width = max(self.winfo_width(), 160)
        visible_rows = min(max(len(self.values), 1), 8)
        row_height = 28
        height = visible_rows * row_height + 2
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=COLORS["border"])
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.transient(self.winfo_toplevel())

        listbox = tk.Listbox(
            popup,
            bg=COLORS["field"],
            fg=COLORS["text"],
            selectbackground=COLORS["accent"],
            selectforeground=COLORS["text"],
            highlightthickness=0,
            bd=0,
            activestyle="none",
            exportselection=False,
            font=("Helvetica", 13),
        )
        listbox.pack(fill="both", expand=True, padx=1, pady=1)
        for value in self.values:
            listbox.insert("end", value)
        if self._current_index >= 0:
            listbox.selection_set(self._current_index)
            listbox.see(self._current_index)

        def select_current(_event=None):
            selection = listbox.curselection()
            if selection:
                self.current(selection[0])
                self.event_generate("<<ComboboxSelected>>")
            self._close_popup()
            return "break"

        listbox.bind("<ButtonRelease-1>", select_current)
        listbox.bind("<Return>", select_current)
        listbox.bind("<Escape>", lambda _event: self._close_popup())
        popup.bind("<FocusOut>", lambda _event: self._close_popup())
        self._popup = popup
        popup.after(10, listbox.focus_force)

    def _close_popup(self):
        popup = self._popup
        self._popup = None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass


class CheckToggle(tk.Frame):
    def __init__(self, parent, text, variable):
        super().__init__(parent, bg=COLORS["panel"])
        self.variable = variable
        self.enabled = True
        self.box = tk.Canvas(self, width=16, height=16, bg=COLORS["panel"], highlightthickness=0, bd=0)
        self.box.grid(row=0, column=0, padx=(0, 10))
        self.label = tk.Label(self, text=text, bg=COLORS["panel"], fg=COLORS["subtle"], font=("Helvetica", 13), cursor="hand2")
        self.label.grid(row=0, column=1, sticky="w")
        self.box.bind("<Button-1>", self.toggle)
        self.label.bind("<Button-1>", self.toggle)
        self.bind("<Button-1>", self.toggle)
        self.draw()

    def draw(self):
        self.box.delete("all")
        outline = COLORS["border"] if self.enabled else COLORS["line"]
        fill = COLORS["accent"] if self.variable.get() else COLORS["panel"]
        self.box.create_rectangle(2, 2, 14, 14, outline=outline, fill=fill, width=1)
        if self.variable.get():
            self.box.create_line(5, 8, 7, 10, 11, 5, fill="#ffffff", width=2)
        self.label.configure(fg=(COLORS["muted"] if self.enabled else COLORS["subtle"]))

    def toggle(self, _event=None):
        if not self.enabled:
            return
        self.variable.set(not self.variable.get())
        self.draw()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.label.configure(cursor=("hand2" if enabled else "arrow"))
        self.draw()


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
    root.title("macOS Desktop Audio Translator")
    root.geometry("560x520")
    root.minsize(520, 420)
    root.configure(bg=COLORS["bg"])
    root.option_add("*Font", "Helvetica 13")

    status_var = tk.StringVar(value="Ready")
    summary_var = tk.StringVar(value="")
    device_var = tk.StringVar(value="")
    src_var = tk.StringVar(value="Arabic")
    tgt_var = tk.StringVar(value="English")
    whisper_var = tk.StringVar(value="openai/whisper-small")
    offline_only_var = tk.BooleanVar(value=False)
    settings_open = tk.BooleanVar(value=True)

    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)

    shell = tk.Frame(root, bg=COLORS["bg"])
    shell.grid(row=0, column=0, rowspan=2, sticky="nsew")
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(1, weight=1)

    settings_card = tk.Frame(shell, bg=COLORS["panel"], padx=20, pady=16)
    settings_card.grid(row=0, column=0, sticky="ew")
    settings_card.columnconfigure(0, weight=1)

    settings_header = tk.Frame(settings_card, bg=COLORS["panel"])
    settings_header.grid(row=0, column=0, sticky="ew")
    settings_header.columnconfigure(1, weight=1)

    settings_body = tk.Frame(settings_card, bg=COLORS["panel"])
    settings_body.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    settings_body.columnconfigure(1, weight=1)

    action_row = tk.Frame(settings_card, bg=COLORS["panel"])
    action_row.grid(row=2, column=0, sticky="ew", pady=(12, 4))
    action_row.columnconfigure(0, weight=1)
    action_row.columnconfigure(1, weight=1)

    output_frame = tk.Frame(shell, bg=COLORS["output"], highlightbackground=COLORS["line"], highlightthickness=1)
    output_frame.grid(row=1, column=0, sticky="nsew")
    output_frame.columnconfigure(0, weight=1)
    output_frame.rowconfigure(0, weight=1)

    log_text = tk.Text(
        output_frame,
        bg=COLORS["output"],
        fg=COLORS["muted"],
        insertbackground=COLORS["text"],
        relief="flat",
        borderwidth=0,
        highlightthickness=0,
        padx=16,
        pady=14,
        wrap="word",
        state="disabled",
        font=("Menlo", 12),
    )
    log_text.grid(row=0, column=0, sticky="nsew")
    log_text.tag_configure("log", foreground=COLORS["muted"])
    log_text.tag_configure("muted", foreground=COLORS["subtle"])
    log_text.tag_configure("source", foreground=COLORS["text"])
    log_text.tag_configure("target", foreground=COLORS["accent"])
    log_text.tag_configure("success", foreground=COLORS["success"])
    log_text.tag_configure("error", foreground=COLORS["error"])

    scrollbar = tk.Scrollbar(
        output_frame,
        orient="vertical",
        command=log_text.yview,
        bg=COLORS["field"],
        activebackground=COLORS["border"],
        troughcolor=COLORS["output"],
        relief="flat",
        bd=0,
        width=10,
        highlightthickness=0,
    )
    scrollbar.grid(row=0, column=1, sticky="ns")

    def sync_scrollbar(first, last):
        scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            scrollbar.grid_remove()
        else:
            scrollbar.grid()

    log_text.configure(yscrollcommand=sync_scrollbar)

    devices = []
    transcriber_holder = {"obj": None, "starting": False}

    def safe_after(callback):
        try:
            root.after(0, callback)
        except tk.TclError:
            pass

    def append_line(line, tag="log"):
        if line is None:
            return
        line = str(line).strip()
        if not line:
            return
        log_text.configure(state="normal")
        log_text.insert("end", line + "\n", tag)
        log_text.see("end")
        log_text.configure(state="disabled")

    def append_from_thread(line, tag="muted"):
        safe_after(lambda line=line, tag=tag: append_line(line, tag))

    def save_device_for_gui(device_name):
        writer = TkLogWriter(lambda line: append_line(line, "muted"))
        with redirect_stdout(writer), redirect_stderr(writer):
            save_device_config(device_name)
        writer.flush()

    def set_status(message, level="idle"):
        colors = {
            "idle": COLORS["subtle"],
            "active": COLORS["accent"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"],
        }
        status_var.set(message)
        status_dot.configure(fg=colors.get(level, COLORS["subtle"]))

    def lang_entry_by_name(name):
        for n, bcp47, iso639 in LANGUAGES:
            if n == name:
                return n, bcp47, iso639
        return None

    def selected_device_name():
        idx = device_combo.current()
        if 0 <= idx < len(devices):
            return devices[idx].name
        return device_var.get() or "No device"

    def update_summary(*_):
        summary_var.set(f"{selected_device_name()}  |  {src_var.get()} -> {tgt_var.get()}  |  {whisper_var.get()}")

    def make_label(parent, text, row):
        label = tk.Label(parent, text=text, bg=COLORS["panel"], fg=COLORS["muted"], anchor="w")
        label.grid(row=row, column=0, sticky="w", padx=(0, 14), pady=6)
        return label

    def make_button(parent, text, command, bg=None, fg=None, border=None, font_weight="normal", padx=14, pady=7, font_size=13):
        bg = bg or COLORS["field"]
        fg = fg or COLORS["text"]
        border = border or COLORS["border"]
        return AppButton(parent, text, command, bg=bg, fg=fg, border=border, font_weight=font_weight, padx=padx, pady=pady, font_size=font_size)

    def set_button_enabled(button, enabled, bg=None, fg=None):
        if hasattr(button, "set_enabled"):
            if bg is not None or fg is not None:
                button.set_colors(bg=bg, fg=fg)
            button.set_enabled(enabled)
            return
        button.configure(state=("normal" if enabled else "disabled"))
        if bg is not None:
            button.configure(bg=bg, activebackground=bg)
        if fg is not None:
            button.configure(fg=fg, activeforeground=fg)

    def toggle_settings(_event=None):
        if settings_open.get():
            settings_body.grid_remove()
            settings_toggle.configure(text="Settings ▸")
            settings_open.set(False)
        else:
            settings_body.grid()
            settings_toggle.configure(text="Settings ▾")
            settings_open.set(True)

    settings_toggle = tk.Label(
        settings_header,
        text="Settings ▾",
        bg=COLORS["panel"],
        fg=COLORS["muted"],
        cursor="hand2",
        font=("Helvetica", 12),
        padx=0,
        pady=0,
    )
    settings_toggle.bind("<Button-1>", toggle_settings)
    settings_toggle.grid(row=0, column=0, sticky="w", padx=(0, 8))
    summary_label = tk.Label(settings_header, textvariable=summary_var, bg=COLORS["panel"], fg=COLORS["subtle"], anchor="e", font=("Menlo", 11))
    summary_label.bind("<Button-1>", toggle_settings)
    summary_label.grid(row=0, column=1, sticky="ew")

    make_label(settings_body, "Audio Device", 0)
    device_combo = FlatCombobox(settings_body, textvariable=device_var, state="readonly")
    device_combo.grid(row=0, column=1, sticky="ew", pady=6)
    btn_refresh = make_button(settings_body, "Refresh", lambda: refresh_devices(), bg=COLORS["field"], padx=13, pady=6)
    btn_refresh.grid(row=0, column=2, sticky="e", padx=(10, 0), pady=6)

    make_label(settings_body, "Speech (source)", 1)
    src_combo = FlatCombobox(settings_body, textvariable=src_var, state="readonly", values=[n for n, _, __ in LANGUAGES])
    src_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)

    make_label(settings_body, "Translate to", 2)
    tgt_combo = FlatCombobox(settings_body, textvariable=tgt_var, state="readonly", values=[n for n, _, __ in LANGUAGES])
    tgt_combo.grid(row=2, column=1, columnspan=2, sticky="ew", pady=6)

    make_label(settings_body, "Whisper model", 3)
    whisper_combo = FlatCombobox(settings_body, textvariable=whisper_var, state="readonly", values=WHISPER_MODELS)
    whisper_combo.grid(row=3, column=1, columnspan=2, sticky="ew", pady=6)

    separator = tk.Frame(settings_body, bg=COLORS["line"], height=1)
    separator.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 10))

    controls_row = tk.Frame(settings_body, bg=COLORS["panel"])
    controls_row.grid(row=5, column=0, columnspan=3, sticky="ew")
    controls_row.columnconfigure(1, weight=1)

    offline_chk = CheckToggle(controls_row, "Offline mode (no downloads)", offline_only_var)
    offline_chk.grid(row=0, column=0, sticky="w")

    btn_download = make_button(controls_row, "Download models", lambda: download_models(), bg=COLORS["panel"], fg=COLORS["accent"], border=COLORS["accent"], padx=13, pady=6, font_size=12)
    btn_download.grid(row=0, column=1, sticky="e", padx=(12, 10))

    status_group = tk.Frame(controls_row, bg=COLORS["panel"], width=108, height=28)
    status_group.grid(row=0, column=2, sticky="e")
    status_group.grid_propagate(False)
    status_group.rowconfigure(0, weight=1)
    status_dot = tk.Label(status_group, text="●", bg=COLORS["panel"], fg=COLORS["subtle"], font=("Helvetica", 12))
    status_dot.grid(row=0, column=0, padx=(0, 6), sticky="w")
    status_label = tk.Label(status_group, textvariable=status_var, bg=COLORS["panel"], fg=COLORS["subtle"], font=("Helvetica", 12))
    status_label.grid(row=0, column=1, sticky="w")

    btn_start = make_button(action_row, "\u25ce  Start Translation", lambda: start(), bg=COLORS["accent"], fg="#ffffff", border=COLORS["accent"], font_weight="bold")
    btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    btn_stop = make_button(action_row, "\u25ce  Stop", lambda: stop(), bg=COLORS["panel"], fg=COLORS["text"], border=COLORS["border"], font_weight="bold")
    btn_stop.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    for combo in (device_combo, src_combo, tgt_combo, whisper_combo):
        combo.bind("<<ComboboxSelected>>", update_summary)

    def refresh_devices():
        nonlocal devices
        try:
            devices = sc.all_microphones(include_loopback=True)
        except Exception as e:
            append_line(f"Unable to list devices: {e}", "error")
            set_status("Device error", "error")
            devices = []
        display = []
        for d in devices:
            tag = device_type_label(d)
            display.append(f"{d.name} [{tag}]")
        device_combo["values"] = display

        saved_device_name = load_device_config()
        selected_idx = None
        if saved_device_name:
            for i, d in enumerate(devices):
                if d.name == saved_device_name:
                    selected_idx = i
                    break
        if selected_idx is None:
            for i, device in enumerate(devices):
                if is_desktop_audio_device(device):
                    selected_idx = i
                    break
        if selected_idx is None and display:
            selected_idx = 0
        if selected_idx is not None:
            device_combo.current(selected_idx)
        update_summary()

    def on_event(event_type, payload):
        def handle():
            if event_type == "status":
                value = str(payload)
                labels = {
                    "transcribing": ("Transcribing", "active"),
                    "translating": ("Translating", "active"),
                }
                text, level = labels.get(value, (value, "active"))
                set_status(text, level)
            elif event_type == "log":
                append_line(payload, "log")
            elif event_type == "error":
                set_status("Error", "error")
                append_line(f"Error: {payload}", "error")
            elif event_type == "transcript":
                try:
                    src_text = payload.get("arabic_text", "")
                    tgt_text = payload.get("english_text", "")
                except Exception:
                    src_text = ""
                    tgt_text = ""
                if src_text:
                    append_line(f"Source: {src_text}", "source")
                if tgt_text:
                    append_line(f"Target: {tgt_text}", "target")
                append_line("-" * 40, "muted")
        safe_after(handle)

    def set_controls_locked(locked, stop_enabled=False):
        combo_state = "disabled" if locked else "readonly"
        device_combo.configure(state=combo_state)
        src_combo.configure(state=combo_state)
        tgt_combo.configure(state=combo_state)
        whisper_combo.configure(state=combo_state)
        offline_chk.set_enabled(not locked)
        set_button_enabled(btn_refresh, not locked)
        set_button_enabled(btn_download, not locked)
        set_button_enabled(btn_start, not locked, bg=(COLORS["accent"] if not locked else "#125a9e"), fg="#ffffff")
        set_button_enabled(btn_stop, stop_enabled)

    def capture_to_log():
        writer = TkLogWriter(lambda line: append_from_thread(line, "muted"))
        return redirect_stdout(writer), redirect_stderr(writer), writer

    def download_models():
        if transcriber_holder["obj"] is not None or transcriber_holder["starting"]:
            return

        src_entry = lang_entry_by_name(src_var.get())
        tgt_entry = lang_entry_by_name(tgt_var.get())
        if not src_entry or not tgt_entry:
            messagebox.showwarning("Language", "Choose source and target languages.")
            return
        if src_entry[2] == tgt_entry[2]:
            messagebox.showwarning("Language", "Source and target languages must be different.")
            return
        _, _, src_iso = src_entry
        _, _, tgt_iso = tgt_entry
        model_name = translation_model_for(src_iso, tgt_iso)
        whisper_model = whisper_var.get().strip() or "openai/whisper-small"

        save_language_config(src_iso, tgt_iso, whisper_model)
        set_controls_locked(True, stop_enabled=False)
        set_status("Downloading", "active")
        append_line(f"Downloading: {whisper_model} + {model_name}", "log")

        def run_download():
            out_ctx, err_ctx, writer = capture_to_log()
            try:
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                with out_ctx, err_ctx:
                    from transformers import pipeline
                    _asr = pipeline("automatic-speech-recognition", model=whisper_model, device=-1)
                    _tr = pipeline("translation", model=model_name, device=-1)
                    _ = _asr
                    _ = _tr
                writer.flush()
                safe_after(lambda: append_line(f"Downloaded: {whisper_model} + {model_name}", "success"))
                safe_after(lambda: set_status("Downloaded", "success"))
            except Exception as e:
                writer.flush()
                error_message = str(e)
                safe_after(lambda: append_line(f"Download failed: {error_message}", "error"))
                safe_after(lambda: set_status("Download failed", "error"))
            finally:
                safe_after(lambda: set_controls_locked(False, stop_enabled=False))

        threading.Thread(target=run_download, daemon=True).start()

    def start():
        if transcriber_holder["obj"] is not None or transcriber_holder["starting"]:
            return

        idx = device_combo.current()
        if idx < 0 or idx >= len(devices):
            messagebox.showwarning("Device", "Select an audio device first.")
            return
        selected = devices[idx]
        save_device_for_gui(selected.name)

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
        update_summary()
        if offline_only_var.get():
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            os.environ["OFFLINE_ONLY"] = "1"
        else:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            os.environ["OFFLINE_ONLY"] = "0"

        append_line(f"Device: {selected.name}", "log")
        append_line(f"Speech: {src_var.get()} -> Translate to: {tgt_var.get()}", "log")
        append_line(f"Models: {whisper_model} + {translation_model}", "log")
        append_line("", "muted")

        transcriber_holder["starting"] = True
        set_controls_locked(True, stop_enabled=False)
        set_status("Loading models", "active")

        def run_start():
            out_ctx, err_ctx, writer = capture_to_log()
            try:
                with out_ctx, err_ctx:
                    transcriber = ArabicAudioTranscriber(
                        selected_device=selected,
                        on_event=on_event,
                        interactive=False,
                        asr_language=src_bcp47,
                        translation_model=translation_model,
                    )
                writer.flush()
            except Exception as e:
                writer.flush()
                error_message = str(e)
                def fail():
                    transcriber_holder["starting"] = False
                    append_line(f"Failed to start: {error_message}", "error")
                    set_controls_locked(False, stop_enabled=False)
                    set_status("Start failed", "error")
                safe_after(fail)
                return

            transcriber_holder["obj"] = transcriber
            transcriber_holder["starting"] = False
            transcriber.start_background(enable_keyboard_shortcuts=False)

            def ready():
                set_status("Running", "active")
                set_controls_locked(True, stop_enabled=True)
            safe_after(ready)

        threading.Thread(target=run_start, daemon=True).start()

    def stop():
        transcriber = transcriber_holder["obj"]
        if transcriber is None:
            return
        set_status("Stopping", "warning")
        set_button_enabled(btn_stop, False)
        transcriber.stop_background()

        def finalize():
            transcriber.join_background()
            transcriber.save_transcript()
            transcriber_holder["obj"] = None
            safe_after(lambda: set_controls_locked(False, stop_enabled=False))
            safe_after(lambda: set_status("Ready", "idle"))

        threading.Thread(target=finalize, daemon=True).start()

    def on_close():
        if transcriber_holder["obj"] is not None:
            stop()
        root.after(300, root.destroy)

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
    whisper_var.set(whisper_model if whisper_model in WHISPER_MODELS else "openai/whisper-small")

    set_controls_locked(False, stop_enabled=False)
    refresh_devices()
    append_line("ready for processing...", "muted")
    set_status("Ready", "idle")
    root.mainloop()


if __name__ == "__main__":
    gui_main()
