"""Non-activating desktop captions; all OS calls have an injectable boundary."""
from ui_scale import px, scaled_geometry
from dataclasses import dataclass
import ctypes
import re
import sys
import time
import tkinter as tk

from engines.display import display_text, dominant_rtl

WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TRANSPARENT = 0x80000, 0x80, 0x8000000, 0x20


@dataclass(frozen=True)
class Monitor:
    name: str
    left: int
    top: int
    right: int
    bottom: int


class Win32Overlay:
    def __init__(self, *, user32=None, gdi32=None):
        self.user32 = user32 or (ctypes.windll.user32 if sys.platform == "win32" else None)
        self.gdi32 = gdi32 or (ctypes.windll.gdi32 if sys.platform == "win32" else None)
        if user32 is None and self.user32:
            for name in ("GetWindowLongPtrW", "SetWindowLongPtrW"):
                getattr(self.user32, name).restype = ctypes.c_ssize_t
            self.user32.GetParent.restype = ctypes.c_void_p
            self.user32.GetParent.argtypes = [ctypes.c_void_p]
            self.user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            self.user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
            self.user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self.user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self.user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            self.gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p

    def handle(self, window):
        handle = window.winfo_id()
        return self.user32.GetParent(handle) or handle

    def apply(self, window, *, click_through=True, hide_from_capture=False):
        if not self.user32:
            return
        handle = self.handle(window)
        style = self.user32.GetWindowLongPtrW(handle, -20)
        style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        style = style | WS_EX_TRANSPARENT if click_through else style & ~WS_EX_TRANSPARENT
        self.user32.SetWindowLongPtrW(handle, -20, style)
        self.user32.SetWindowDisplayAffinity(handle, 0x11 if hide_from_capture else 0)
        region = self.gdi32.CreateRoundRectRgn(0, 0, window.winfo_width()+1, window.winfo_height()+1, 20, 20)
        if region and not self.user32.SetWindowRgn(handle, region, True):
            self.gdi32.DeleteObject(region)

    def show(self, window):
        window.deiconify()
        if self.user32:
            self.user32.SetWindowPos(self.handle(window), -1, 0, 0, 0, 0, 0x13)  # no move/size/activate

    def cursor(self):
        if not self.user32:
            return None
        from ctypes.wintypes import POINT
        point = POINT()
        return (point.x, point.y) if self.user32.GetCursorPos(ctypes.byref(point)) else None

    def monitors(self, root):
        if not self.user32:
            return [Monitor("primary", 0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
        from ctypes.wintypes import RECT, DWORD
        class Info(ctypes.Structure):
            _fields_ = [("size", DWORD), ("monitor", RECT), ("work", RECT), ("flags", DWORD), ("name", ctypes.c_wchar*32)]
        result = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_ssize_t)
        def collect(handle, dc, rect, data):
            info = Info()
            info.size = ctypes.sizeof(info)
            if self.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                work = info.work
                item = Monitor(info.name, work.left, work.top, work.right, work.bottom)
                result.insert(0, item) if info.flags & 1 else result.append(item)
            return True
        self.user32.EnumDisplayMonitors(None, None, callback_type(collect), 0)
        return result or [Monitor("primary", 0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]

    def meeting_window_center(self, pid):
        if not self.user32:
            return None
        from ctypes.wintypes import DWORD, RECT
        self.user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(DWORD)]
        self.user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
        result = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t)
        def visit(handle, extra):
            owner, rectangle = DWORD(), RECT()
            self.user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
            if owner.value == pid and self.user32.IsWindowVisible(handle) and self.user32.GetWindowRect(handle, ctypes.byref(rectangle)):
                result.append(((rectangle.left+rectangle.right)//2, (rectangle.top+rectangle.bottom)//2))
                return False
            return True
        self.user32.EnumWindows(callback_type(visit), 0)
        return result[0] if result else None


class SubtitleOverlay:
    def __init__(self, root, preferences, colors, *, backend=None, clock=time.monotonic, on_hide=lambda: None,
                 on_open=lambda: None):
        self.root, self.preferences, self.colors = root, preferences, colors
        self.backend, self.clock = backend or Win32Overlay(), clock
        self.on_hide, self.on_open = on_hide, on_open
        self.window = tk.Toplevel(root)
        from windows_icons import apply_window_icon
        self.window.after_idle(lambda: apply_window_icon(self.window))
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.configure(bg=colors["black"])
        self.toolbar = tk.Frame(self.window, bg=colors["black"])
        for label, command in (("Pause", self.pause), ("−", lambda: self.resize_text(-2)), ("+", lambda: self.resize_text(2)),
                               ("Move", self.enable_move), ("Open app", on_open), ("Hide", on_hide)):
            tk.Button(self.toolbar, text=label, command=command, bg=colors["black"], fg=colors["secondary"],
                activebackground=colors["field"], activeforeground=colors["text"], relief="flat", bd=0, padx=px(8), pady=px(3)).pack(side="left")
        self.content = tk.Frame(self.window, bg=colors["black"], padx=px(16), pady=px(10))
        self.content.pack(fill="both", expand=True)
        self.labels = [tk.Label(self.content, bg=colors["black"], fg=colors["text"], wraplength=px(688), justify="center") for _ in range(4)]
        self.reply_tray = tk.Frame(self.window, bg=colors["black"], padx=px(12), pady=px(8))
        self.entries, self.last_text = [], ""
        self.updated, self.paused, self.hovering = None, False, False
        self.monitor = self.backend.monitors(root)[0]
        self.window.geometry(scaled_geometry("720x90"))
        self.restore_position(self.monitor)
        self.window.bind("<ButtonPress-1>", self.drag_start)
        self.window.bind("<B1-Motion>", self.drag)
        self.window.bind("<ButtonRelease-1>", self.drag_end)
        self.window.update_idletasks()
        self.window.geometry(f"{px(720)}x{max(px(64), self.window.winfo_reqheight())}")
        self.apply_styles()

    def option(self, key, default):
        return self.preferences.get("SUBTITLES", key, default)

    def apply_styles(self):
        self.window.attributes("-alpha", min(1.0, max(.2, self.option("background_alpha", .9))))
        self.backend.apply(self.window, click_through=self.option("click_through", True) and not self.hovering,
                           hide_from_capture=self.option("hide_from_capture", False))

    def accept(self, entry):
        if not entry.get("source_text") and not entry.get("translated_text"):
            return
        existing = next((e for e in self.entries if e.get("id") == entry.get("id")), None)
        if existing is not None:
            existing.update(entry)
        else:
            self.entries.append(entry.copy())
            self.entries = self.entries[-3:]
        text = (entry.get("source_text", ""), entry.get("translated_text", ""))
        if text != self.last_text:
            self.updated, self.last_text = self.clock(), text
        self.render()

    def render(self):
        if self.paused:
            return
        for label in self.labels:
            label.pack_forget()
        count = min(3, max(1, self.option("lines", 2)))
        size = min(48, max(12, self.option("text_size", 24)))
        rows = self.entries[-count:]
        for index, entry in enumerate(rows):
            label = self.labels[index]
            text = entry.get("translated_text") or entry.get("source_text", "")
            current = index == len(rows)-1
            label.configure(text=display_text(text), font=("Segoe UI Semibold" if current else "Segoe UI", round(size*.75 if current else size*.56)),
                fg=self.colors["secondary"] if not current or entry.get("translation_pending") else self.colors["text"])
            from engines.display import configure_language_text
            code = entry.get("target_language") if entry.get("translated_text") else entry.get("source_language")
            configure_language_text(label, text, code, round(size*.75 if current else size*.56), semibold=current)
            label.pack(fill="x", pady=px(2))
        if rows and self.option("show_original", False) and rows[-1].get("translated_text"):
            self.labels[3].configure(text=display_text(rows[-1].get("source_text", "")), fg=self.colors["secondary"], font=("Segoe UI", 10))
            configure_language_text(self.labels[3], rows[-1].get("source_text", ""), rows[-1].get("source_language"), 10)
            self.labels[3].pack(fill="x", pady=px(2))
        self.window.update_idletasks()
        self.window.geometry(f"{px(720)}x{max(px(64), self.window.winfo_reqheight())}")
        self.apply_styles()

    def visible(self, enabled, *, listening, minimized):
        show = enabled and listening and (self.option("show_when", "listening") == "listening" or minimized)
        fade = self.option("fade_seconds", 6.0)
        show = show and self.updated is not None and (fade <= 0 or self.clock()-self.updated <= fade)
        if show:
            self.backend.show(self.window)
        else:
            self.window.withdraw()

    def hover(self):
        cursor = self.backend.cursor()
        inside = cursor is not None and self.window.winfo_rootx() <= cursor[0] <= self.window.winfo_rootx()+self.window.winfo_width() and self.window.winfo_rooty() <= cursor[1] <= self.window.winfo_rooty()+self.window.winfo_height()
        if inside != self.hovering:
            self.hovering = inside
            self.toolbar.pack(fill="x", before=self.content) if inside else self.toolbar.pack_forget()
            self.apply_styles()

    def pause(self):
        self.paused = not self.paused
        self.render()

    def resize_text(self, change):
        self.preferences.set("SUBTITLES", "text_size", min(48, max(12, self.option("text_size", 24)+change)))
        self.render()

    def enable_move(self):
        self.hovering = True
        self.backend.apply(self.window, click_through=False, hide_from_capture=self.option("hide_from_capture", False))

    @staticmethod
    def position_key(monitor):
        return "position_" + re.sub(r"[^a-z0-9_]", "_", monitor.name.casefold())

    def restore_position(self, monitor):
        self.monitor = monitor
        value = self.preferences.get("SUBTITLES", self.position_key(monitor), "")
        match = re.fullmatch(r"(-?\d+),(-?\d+)", value)
        x, y = map(int, match.groups()) if match else ((monitor.left+monitor.right-px(720))//2, monitor.bottom-px(170))
        x = max(monitor.left, min(x, monitor.right-px(720)))
        y = max(monitor.top, min(y, monitor.bottom-px(120)))
        self.window.geometry(f"{px(720)}x{px(90)}{x:+d}{y:+d}")

    def drag_start(self, event):
        self._drag = event.x_root-self.window.winfo_x(), event.y_root-self.window.winfo_y()

    def drag(self, event):
        if hasattr(self, "_drag"):
            x, y = event.x_root-self._drag[0], event.y_root-self._drag[1]
            self.window.geometry(f"{x:+d}{y:+d}")

    def drag_end(self, event):
        x, y = self.window.winfo_x(), self.window.winfo_y()
        monitor = next((m for m in self.backend.monitors(self.root) if m.left <= x < m.right and m.top <= y < m.bottom), self.monitor)
        self.monitor = monitor
        self.preferences.set("SUBTITLES", self.position_key(monitor), f"{x},{y}")


class PreviewBackend:
    def apply(self, *args, **kwargs): pass
    def show(self, window): window.deiconify()
    def cursor(self): return None
    def monitors(self, root): return [Monitor("primary", 0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]


class SubtitleController:
    def __init__(self, app, colors, *, backend=None, clock=time.monotonic):
        self.app, self.colors, self.clock = app, colors, clock
        self.backend = backend or (PreviewBackend() if app.preview_mode else Win32Overlay())
        self.overlay, self.timer = None, None
        app.subtitles_enabled_var.trace_add("write", lambda *_: self.tick(schedule=False))
        self.tick()

    def ensure_overlay(self):
        if self.overlay is None:
            self.overlay = SubtitleOverlay(self.app.root, self.app.preferences, self.colors, backend=self.backend,
                clock=self.clock, on_hide=lambda: self.set_enabled(False), on_open=self.app.show_main_window)
        return self.overlay

    def set_enabled(self, enabled, origin="main"):
        self.app.subtitles_enabled_var.set(bool(enabled))
        self.app.refresh_tray_menu()

    def toggle(self, origin="hotkey"):
        self.set_enabled(not self.app.subtitles_enabled_var.get(), origin)

    def accept(self, entry):
        if self.app.subtitles_enabled_var.get():
            self.ensure_overlay().accept(entry)
            self.tick(schedule=False)

    def tick(self, *, schedule=True):
        app = self.app
        if app.is_quitting:
            return
        if app.subtitles_enabled_var.get():
            overlay = self.ensure_overlay()
            meeting = getattr(app, "meeting_source", None)
            if meeting and hasattr(self.backend, "meeting_window_center"):
                center = self.backend.meeting_window_center(meeting.pid)
                if center:
                    monitor = next((m for m in self.backend.monitors(app.root) if m.left <= center[0] < m.right and m.top <= center[1] < m.bottom), overlay.monitor)
                    if monitor.name != overlay.monitor.name:
                        overlay.restore_position(monitor)
            overlay.render()
            if hasattr(app,"reply_controller"):
                app.reply_controller.render_overlay()
            minimized = app.root.state() == "iconic" or not app.root.winfo_viewable()
            overlay.visible(True, listening=app.transcriber is not None and app.mode_var.get() == "listen", minimized=minimized)
            overlay.hover()
        elif self.overlay:
            self.overlay.window.withdraw()
        if schedule:
            self.timer = app.root.after(200, self.tick)

    def close(self):
        if self.timer:
            self.app.root.after_cancel(self.timer)
        if self.overlay and self.overlay.window.winfo_exists():
            self.overlay.window.destroy()


def build_subtitle_page(app, colors):
    from engine_ui import heading, field
    from ui_widgets import Switch
    page = app.settings_shell.contents["Subtitles"]
    heading(page, "Subtitles on screen", "Show translations over any window, including when Translito is minimized to the tray.", colors)
    row = tk.Frame(page, bg=colors["bg"])
    row.pack(fill="x", pady=px(10))
    tk.Label(row, text="Show subtitles on screen", bg=colors["bg"], fg=colors["text"]).pack(side="left")
    Switch(row, app.subtitles_enabled_var, colors).pack(side="right")
    preview = tk.Label(page, text="Previous translation\nCurrent translation", bg=colors["black"], fg=colors["text"], font=("Segoe UI", 12), pady=px(16))
    preview.pack(fill="x", pady=px(14))
    for key, label, default, values in (
        ("show_when", "Show", "listening", ("listening", "minimized")),
        ("lines", "Lines", 2, (1,2,3)), ("text_size", "Text size", 24, (16,20,24,28,32,40,48)),
        ("background_alpha", "Background opacity", .9, (.5,.7,.9,1.0)),
        ("fade_seconds", "Fade after seconds without speech (0 = never)", 6, (0,3,6,10,20))):
        variable = tk.IntVar(app.root) if isinstance(default,int) else tk.DoubleVar(app.root) if isinstance(default,float) else tk.StringVar(app.root)
        app.preferences.bind(variable, "SUBTITLES", key, default)
        field(page, label, variable, colors, values)
    for key, label, default in (("show_original", "Show the original line", False),
        ("click_through", "Let clicks pass through to the window underneath", True),
        ("hide_from_capture", "Hide subtitles from screen sharing", False)):
        variable = app.preferences.bind(tk.BooleanVar(app.root), "SUBTITLES", key, default)
        tk.Checkbutton(page, text=label, variable=variable, **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(anchor="w", pady=px(6))
