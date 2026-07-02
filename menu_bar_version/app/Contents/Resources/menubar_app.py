#!/usr/bin/env python3
import configparser
import os
import shutil
import subprocess
import sys
import threading
import warnings
from pathlib import Path

import objc
from Foundation import NSMakeRange
from AppKit import (
    NSApplication,
    NSAppearance,
    NSAppearanceNameVibrantDark,
    NSBackingStoreBuffered,
    NSBorderlessWindowMask,
    NSButton,
    NSCenterTextAlignment,
    NSColor,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSMakePoint,
    NSMakeRect,
    NSMomentaryPushInButton,
    NSObject,
    NSPanel,
    NSPopUpButton,
    NSRoundedBezelStyle,
    NSNoBorder,
    NSScrollView,
    NSScreen,
    NSStatusBar,
    NSStatusWindowLevel,
    NSTextField,
    NSTextView,
    NSView,
    NSVariableStatusItemLength,
    NSSwitchButton,
)
from PyObjCTools import AppHelper

warnings.filterwarnings("ignore", category=getattr(objc, "ObjCPointerWarning", Warning))
os.environ.setdefault("DAT_DISABLE_KEYBOARD", "1")

APP_NAME = "Desktop Audio Translator Menu Bar"
RESOURCE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = Path(os.environ.get("DAT_SOURCE_DIR", RESOURCE_DIR / "src")).resolve()
APP_BUNDLE = Path(os.environ.get("DAT_APP_BUNDLE", RESOURCE_DIR.parents[1])).resolve()
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
LOG_DIR = Path.home() / "Library" / "Logs" / APP_NAME
CONFIG_FILE = APP_SUPPORT_DIR / "config.ini"

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

VIRTUAL_AUDIO_NAME_PARTS = (
    "blackhole",
    "soundflower",
    "loopback",
    "background music",
    "vb-cable",
    "audio hijack",
    "rogue amoeba",
    "virtual",
)


def run_osascript(lines):
    command = ["osascript"]
    for line in lines:
        command.extend(["-e", line])
    return subprocess.run(command, capture_output=True, text=True, check=False)


def escape_applescript(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def show_dialog(message, icon="caution"):
    safe_message = escape_applescript(message)
    run_osascript([f'display dialog "{safe_message}" buttons {{"OK"}} default button "OK" with icon {icon}'])


def login_item_names():
    result = run_osascript(['tell application "System Events" to get the name of every login item'])
    if result.returncode != 0:
        return []
    output = result.stdout.strip()
    if not output:
        return []
    return [name.strip() for name in output.split(",")]


def login_item_enabled():
    return APP_NAME in login_item_names()


def set_login_item_enabled(enabled):
    app_path = escape_applescript(APP_BUNDLE)
    if enabled:
        lines = [
            'tell application "System Events"',
            f'if not (exists login item "{APP_NAME}") then',
            f'make login item at end with properties {{path:"{app_path}", hidden:false}}',
            "end if",
            "end tell",
        ]
    else:
        lines = [
            'tell application "System Events"',
            f'if exists login item "{APP_NAME}" then delete login item "{APP_NAME}"',
            "end tell",
        ]
    return run_osascript(lines)


def language_by_iso(iso_code, fallback="ar"):
    for name, bcp47, iso639 in LANGUAGES:
        if iso639 == iso_code:
            return name, bcp47, iso639
    return language_by_iso(fallback, "ar") if iso_code != fallback else LANGUAGES[0]


def language_by_name(language_name):
    for name, bcp47, iso639 in LANGUAGES:
        if name == language_name:
            return name, bcp47, iso639
    return LANGUAGES[0]


def translation_model_for(source_code, target_code):
    return f"Helsinki-NLP/opus-mt-{source_code}-{target_code}"


def is_desktop_audio_name(name):
    lower_name = (name or "").lower()
    return any(part in lower_name for part in VIRTUAL_AUDIO_NAME_PARTS)


def is_desktop_audio_device(device):
    return bool(getattr(device, "isloopback", False)) or is_desktop_audio_name(getattr(device, "name", ""))


def device_type_label(device):
    return "Desktop/Virtual" if is_desktop_audio_device(device) else "Mic"


def ensure_support_files():
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    bundled_config = SOURCE_DIR / "config.ini"
    if bundled_config.exists() and not CONFIG_FILE.exists():
        shutil.copy2(bundled_config, CONFIG_FILE)


def read_config():
    ensure_support_files()
    config = configparser.ConfigParser()
    if CONFIG_FILE.exists():
        config.read(CONFIG_FILE)
    return config


def write_config(config):
    ensure_support_files()
    with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
        config.write(config_file)


class SubtitleOverlay(NSObject):
    def init(self):
        self = objc.super(SubtitleOverlay, self).init()
        if self is None:
            return None
        self.enabled = True
        self.window = None
        self.label = None
        self.last_text = "Ready for translation"
        return self

    def ensure_window(self):
        if self.window is not None:
            return
        screen = NSScreen.mainScreen()
        frame = screen.visibleFrame()
        width = min(980, max(520, frame.size.width - 160))
        height = 96
        x = frame.origin.x + (frame.size.width - width) / 2
        y = frame.origin.y + 46
        rect = NSMakeRect(x, y, width, height)
        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSBorderlessWindowMask,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setLevel_(NSStatusWindowLevel)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setIgnoresMouseEvents_(True)
        self.window.setHasShadow_(True)

        self.label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        self.label.setBordered_(False)
        self.label.setDrawsBackground_(True)
        self.label.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.72))
        self.label.setTextColor_(NSColor.whiteColor())
        self.label.setAlignment_(NSCenterTextAlignment)
        self.label.setFont_(NSFont.boldSystemFontOfSize_(28))
        self.label.setStringValue_(self.last_text)
        try:
            self.label.cell().setWraps_(True)
        except Exception:
            pass
        self.window.contentView().addSubview_(self.label)

    def show(self):
        self.enabled = True
        self.ensure_window()
        self.window.orderFrontRegardless()

    def hide(self):
        self.enabled = False
        if self.window is not None:
            self.window.orderOut_(None)

    def set_text(self, text):
        value = (text or "").strip()
        if not value:
            return
        self.last_text = value
        if not self.enabled:
            return
        self.ensure_window()
        self.label.setStringValue_(value)
        self.window.orderFrontRegardless()

    def clear(self):
        self.last_text = ""
        if self.label is not None:
            self.label.setStringValue_("")


class MenuBarController(NSObject):
    def init(self):
        self = objc.super(MenuBarController, self).init()
        if self is None:
            return None

        ensure_support_files()
        self.runtime = None
        self.devices = []
        self.device_load_error = None
        self.transcriber = None
        self.starting = False
        self.stopping = False
        self.downloading = False
        self.status_text = "Ready"
        self.gui_process = None
        self.lock = threading.RLock()

        self.device_name = ""
        self.source_name = "Arabic"
        self.target_name = "English"
        self.whisper_model = "openai/whisper-small"
        self.offline_only = False
        self.overlay_enabled = True
        self.load_preferences()

        self.subtitle_overlay = SubtitleOverlay.alloc().init()

        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("AT")
        self.status_item.button().setTarget_(self)
        self.status_item.button().setAction_("togglePanel:")
        self.panel = None
        self.panel_width = 319
        self.panel_height = 198
        self.expanded_panel_height = 440
        self.settings_open = False
        self.settings_toggle_button = None
        self.settings_controls = []
        self.title_label = None
        self.footer_view = None
        self.footer_separator = None
        self.status_dot = None
        self.status_label = None
        self.summary_label = None
        self.device_popup = None
        self.source_popup = None
        self.target_popup = None
        self.whisper_popup = None
        self.offline_checkbox = None
        self.overlay_checkbox = None
        self.login_checkbox = None
        self.start_button = None
        self.stop_button = None
        self.download_button = None
        self.compact_button = None
        self.close_compact_button = None
        self.separator = None
        self.log_scroll = None
        self.log_view = None
        self.log_lines = []
        self.build_panel()
        self.refresh_devices()
        self.rebuild_setting_controls()
        self.refresh_panel_state(check_login=False)
        self.append_log("ready for processing...")
        return self

    def build_panel(self):
        width = self.panel_width
        height = self.panel_height
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSBorderlessWindowMask,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameVibrantDark))
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setLevel_(NSStatusWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(True)

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        content.setWantsLayer_(True)
        content_layer = content.layer()
        content_layer.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.12, 1.0).CGColor())
        content_layer.setBorderWidth_(1.0)
        content_layer.setBorderColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.12).CGColor())
        content_layer.setCornerRadius_(14.0)
        self.panel.setContentView_(content)

        self.title_label = self.make_label("AUDIO TRANSLATOR", 12, 172, 150, 16, size=10)
        self.title_label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.42, 1.0))
        content.addSubview_(self.title_label)

        self.status_dot = self.make_dot(16, 146, 8)
        content.addSubview_(self.status_dot)
        self.summary_label = self.make_label("", 31, 140, 190, 22, size=13)
        self.summary_label.setTextColor_(NSColor.whiteColor())
        content.addSubview_(self.summary_label)
        self.status_label = self.make_label("Ready", 258, 140, 48, 22, size=11, mono=True)
        self.status_label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.46, 1.0))
        content.addSubview_(self.status_label)

        self.start_button = self.make_button("●  Start Translation", 16, 69, 287, 36, "primaryAction:", role="primary")
        content.addSubview_(self.start_button)

        self.footer_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 40))
        self.footer_view.setWantsLayer_(True)
        self.footer_view.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.15, 1.0).CGColor())
        content.addSubview_(self.footer_view)
        self.footer_separator = NSView.alloc().initWithFrame_(NSMakeRect(0, 39, width, 1))
        self.footer_separator.setWantsLayer_(True)
        self.footer_separator.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.08).CGColor())
        content.addSubview_(self.footer_separator)

        self.settings_toggle_button = self.make_text_button("Settings", 32, 9, 120, 22, "toggleSettings:")
        content.addSubview_(self.settings_toggle_button)

        self.add_setting_control(content, self.make_label("Audio Device", 16, 282, 140, 18, size=11, bold=True))
        self.device_popup = self.add_setting_control(content, self.make_popup(16, 252, 213, 28, "selectDevicePopup:"))
        self.add_setting_control(content, self.make_button("Refresh", 239, 252, 64, 28, "refreshDevices:"))

        self.add_setting_control(content, self.make_label("Speech", 16, 218, 110, 18, size=11, bold=True))
        self.source_popup = self.add_setting_control(content, self.make_popup(16, 188, 137, 28, "selectSourcePopup:"))
        self.add_setting_control(content, self.make_label("Translate To", 166, 218, 120, 18, size=11, bold=True))
        self.target_popup = self.add_setting_control(content, self.make_popup(166, 188, 137, 28, "selectTargetPopup:"))

        self.add_setting_control(content, self.make_label("Whisper Model", 16, 154, 140, 18, size=11, bold=True))
        self.whisper_popup = self.add_setting_control(content, self.make_popup(16, 124, 287, 28, "selectWhisperPopup:"))

        self.offline_checkbox = self.add_setting_control(content, self.make_checkbox("Offline mode", 16, 91, 130, 24, "toggleOffline:"))
        self.overlay_checkbox = self.add_setting_control(content, self.make_checkbox("Show subtitles", 166, 91, 130, 24, "toggleOverlay:"))
        self.login_checkbox = self.add_setting_control(content, self.make_checkbox("Open at Login", 16, 62, 135, 24, "toggleOpenAtLogin:"))
        self.download_button = self.add_setting_control(content, self.make_button("Download models", 166, 60, 137, 28, "downloadModels:"))
        self.add_setting_control(content, self.make_button("Quit", 239, 8, 64, 24, "quitApp:"))

        self.update_panel_layout()

    def add_setting_control(self, content, control):
        content.addSubview_(control)
        self.settings_controls.append(control)
        return control

    def make_label(self, text, x, y, width, height, size=13, bold=False, mono=False):
        label = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        label.setStringValue_(text)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setBordered_(False)
        label.setDrawsBackground_(False)
        if mono:
            label.setFont_(NSFont.fontWithName_size_("Menlo", size) or NSFont.systemFontOfSize_(size))
        else:
            label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        if bold:
            label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.68, 1.0))
        return label

    def make_pill_label(self, text, x, y, width, height, size=12, bold=False):
        label = self.make_label(text, x, y, width, height, size=size, bold=bold)
        label.setAlignment_(NSCenterTextAlignment)
        label.setTextColor_(NSColor.whiteColor())
        label.setWantsLayer_(True)
        layer = label.layer()
        layer.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.04, 0.48, 1.0, 0.86).CGColor())
        layer.setCornerRadius_(height / 2)
        return label

    def make_dot(self, x, y, size):
        dot = NSView.alloc().initWithFrame_(NSMakeRect(x, y, size, size))
        dot.setWantsLayer_(True)
        dot.layer().setCornerRadius_(size / 2)
        dot.layer().setBackgroundColor_(NSColor.systemBlueColor().CGColor())
        return dot

    def make_text_button(self, title, x, y, width, height, action):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        button.setButtonType_(NSMomentaryPushInButton)
        button.setBordered_(False)
        button.setAlignment_(0)
        button.setFont_(NSFont.systemFontOfSize_(13))
        button.setContentTintColor_(NSColor.colorWithCalibratedWhite_alpha_(0.68, 1.0))
        return button

    def make_button(self, title, x, y, width, height, action, role="secondary"):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        button.setButtonType_(NSMomentaryPushInButton)
        button.setBezelStyle_(NSRoundedBezelStyle)
        button.setWantsLayer_(True)
        if role == "primary":
            button.setBordered_(False)
            button.setContentTintColor_(NSColor.whiteColor())
            button.layer().setBackgroundColor_(NSColor.systemBlueColor().CGColor())
            button.layer().setCornerRadius_(4.0)
        elif role == "link":
            button.setBordered_(False)
            button.setContentTintColor_(NSColor.systemBlueColor())
        else:
            button.layer().setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.13, 1.0).CGColor())
            button.layer().setBorderWidth_(1.0)
            button.layer().setBorderColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.18).CGColor())
            button.layer().setCornerRadius_(4.0)
        return button

    def make_checkbox(self, title, x, y, width, height, action):
        checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        checkbox.setTitle_(title)
        checkbox.setTarget_(self)
        checkbox.setAction_(action)
        checkbox.setButtonType_(NSSwitchButton)
        return checkbox

    def make_popup(self, x, y, width, height, action):
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(x, y, width, height), False)
        popup.setTarget_(self)
        popup.setAction_(action)
        return popup

    def update_panel_layout(self):
        target_height = self.expanded_panel_height if self.settings_open else self.panel_height
        if self.panel is not None:
            frame = self.panel.frame()
            if int(frame.size.height) != int(target_height):
                top = frame.origin.y + frame.size.height
                self.panel.setFrame_display_(NSMakeRect(frame.origin.x, top - target_height, self.panel_width, target_height), True)

        title_y = target_height - 26
        route_y = target_height - 58
        dot_y = target_height - 51
        action_y = target_height - 129 if not self.settings_open else target_height - 115

        if self.title_label is not None:
            self.title_label.setFrame_(NSMakeRect(12, title_y, 150, 16))
        if self.status_dot is not None:
            self.status_dot.setFrame_(NSMakeRect(16, dot_y, 8, 8))
        if self.summary_label is not None:
            self.summary_label.setFrame_(NSMakeRect(31, route_y, 190, 22))
        if self.status_label is not None:
            self.status_label.setFrame_(NSMakeRect(258, route_y, 48, 22))

        for control in self.settings_controls:
            control.setHidden_(not self.settings_open)
        if self.settings_toggle_button is not None:
            self.settings_toggle_button.setTitle_("Settings ▾" if self.settings_open else "Settings")
        if self.start_button is not None:
            self.start_button.setFrame_(NSMakeRect(16, action_y, 287, 36))
        self.refresh_panel_state(check_login=False)

    def toggleSettings_(self, _sender):
        self.settings_open = not self.settings_open
        self.update_panel_layout()

    def togglePanel_(self, _sender):
        if self.panel is not None and self.panel.isVisible():
            self.panel.orderOut_(None)
            return
        self.load_preferences()
        self.rebuild_setting_controls()
        self.refresh_panel_state(check_login=False)
        self.update_panel_layout()
        self.position_panel()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.panel.orderFrontRegardless()

    def append_log(self, line):
        value = str(line or "").strip()
        if not value:
            return
        print(value, flush=True)
        self.log_lines.append(value)
        self.log_lines = self.log_lines[-300:]
        if self.log_view is not None:
            text = "\n".join(self.log_lines)
            self.log_view.setString_(text)
            self.log_view.scrollRangeToVisible_(NSMakeRange(len(text), 0))

    def primaryAction_(self, sender):
        if self.running():
            self.stopTranslation_(sender)
            return
        if self.busy():
            return
        self.startTranslation_(sender)

    def position_panel(self):
        screen = NSScreen.mainScreen()
        screen_frame = screen.visibleFrame()
        panel_frame = self.panel.frame()
        fallback_x = screen_frame.origin.x + screen_frame.size.width - panel_frame.size.width - 16
        fallback_y = screen_frame.origin.y + screen_frame.size.height - panel_frame.size.height - 16
        button_window = self.status_item.button().window()
        if button_window is not None:
            button_frame = button_window.frame()
            x = button_frame.origin.x + button_frame.size.width - panel_frame.size.width - 8
            y = button_frame.origin.y - panel_frame.size.height - 8
            if x <= screen_frame.origin.x + 8 or y <= screen_frame.origin.y + 8:
                x = fallback_x
                y = fallback_y
        else:
            x = fallback_x
            y = fallback_y
        x = max(screen_frame.origin.x + 8, min(x, screen_frame.origin.x + screen_frame.size.width - panel_frame.size.width - 8))
        y = max(screen_frame.origin.y + 8, min(y, screen_frame.origin.y + screen_frame.size.height - panel_frame.size.height - 8))
        self.panel.setFrameOrigin_(NSMakePoint(x, y))

    def running(self):
        return self.transcriber is not None and getattr(self.transcriber, "running", False)

    def busy(self):
        return self.starting or self.stopping or self.downloading

    def set_status(self, text):
        self.status_text = text
        if self.status_label is not None:
            self.status_label.setStringValue_(text)
        if self.running():
            self.status_item.button().setTitle_("AT*")
        elif self.busy():
            self.status_item.button().setTitle_("AT...")
        else:
            self.status_item.button().setTitle_("AT")
        self.refresh_panel_state(check_login=False)

    def refresh_panel_state(self, check_login=True):
        running = self.running()
        locked = running or self.busy()
        self.sync_visual_state()
        for control in (self.device_popup, self.source_popup, self.target_popup, self.whisper_popup, self.offline_checkbox):
            if control is not None:
                control.setEnabled_(not locked)
        if self.start_button is not None:
            if running:
                self.start_button.setTitle_("■  Stop Translation")
                enabled = not self.stopping
                self.style_button(self.start_button, active=enabled, primary=True, danger=True)
            elif self.starting:
                self.start_button.setTitle_("Loading models...")
                enabled = False
                self.style_button(self.start_button, active=False, primary=True)
            elif self.downloading:
                self.start_button.setTitle_("Downloading models...")
                enabled = False
                self.style_button(self.start_button, active=False, primary=True)
            else:
                self.start_button.setTitle_("●  Start Translation")
                enabled = not locked
                self.style_button(self.start_button, active=enabled, primary=True)
            self.start_button.setEnabled_(enabled)
        if self.stop_button is not None:
            self.stop_button.setEnabled_(running and not self.stopping)
            self.style_button(self.stop_button, active=running and not self.stopping, primary=False)
        if self.download_button is not None:
            self.download_button.setEnabled_(not locked)
        if self.offline_checkbox is not None:
            self.offline_checkbox.setState_(NSControlStateValueOn if self.offline_only else NSControlStateValueOff)
        if self.overlay_checkbox is not None:
            self.overlay_checkbox.setState_(NSControlStateValueOn if self.overlay_enabled else NSControlStateValueOff)

        compact_running = self.gui_process is not None and self.gui_process.poll() is None
        if self.compact_button is not None:
            self.compact_button.setTitle_("Show Window" if compact_running else "Open Window")
        if self.close_compact_button is not None:
            self.close_compact_button.setEnabled_(compact_running)
        if check_login and self.login_checkbox is not None:
            self.login_checkbox.setState_(NSControlStateValueOn if login_item_enabled() else NSControlStateValueOff)

    def style_button(self, button, active=True, primary=False, danger=False):
        if button is None or button.layer() is None:
            return
        if primary:
            if danger:
                bg = NSColor.systemRedColor() if active else NSColor.colorWithCalibratedRed_green_blue_alpha_(0.34, 0.12, 0.12, 1.0)
            else:
                bg = NSColor.systemBlueColor() if active else NSColor.colorWithCalibratedRed_green_blue_alpha_(0.05, 0.30, 0.52, 1.0)
            fg = NSColor.whiteColor() if active else NSColor.colorWithCalibratedWhite_alpha_(0.62, 1.0)
            button.layer().setBackgroundColor_(bg.CGColor())
            button.layer().setBorderWidth_(0.0)
            button.setContentTintColor_(fg)
            return
        bg = NSColor.colorWithCalibratedWhite_alpha_(0.13 if active else 0.10, 1.0)
        border = NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.20 if active else 0.10)
        fg = NSColor.colorWithCalibratedWhite_alpha_(0.90 if active else 0.40, 1.0)
        button.layer().setBackgroundColor_(bg.CGColor())
        button.layer().setBorderWidth_(1.0)
        button.layer().setBorderColor_(border.CGColor())
        button.setContentTintColor_(fg)

    def sync_visual_state(self):
        if self.summary_label is not None:
            self.summary_label.setStringValue_(f"{self.source_name} → {self.target_name}")
        if self.status_label is not None:
            if self.running():
                self.status_label.setStringValue_("Active")
            elif self.busy():
                self.status_label.setStringValue_("Busy")
            else:
                self.status_label.setStringValue_("Ready")
        if self.status_dot is None:
            return
        status_lower = self.status_text.lower()
        if self.running():
            color = NSColor.systemGreenColor()
        elif self.busy():
            color = NSColor.systemOrangeColor()
        elif "fail" in status_lower or "error" in status_lower:
            color = NSColor.systemRedColor()
        else:
            color = NSColor.systemBlueColor()
        self.status_dot.layer().setBackgroundColor_(color.CGColor())

    def load_preferences(self):
        config = read_config()
        self.device_name = config.get("DEVICE", "name", fallback=self.device_name or "")
        source_iso = config.get("LANGUAGE", "source", fallback="ar")
        target_iso = config.get("LANGUAGE", "target", fallback="en")
        self.source_name = language_by_iso(source_iso, "ar")[0]
        self.target_name = language_by_iso(target_iso, "en")[0]
        model = config.get("LANGUAGE", "whisper_model", fallback=self.whisper_model)
        self.whisper_model = model if model in WHISPER_MODELS else "openai/whisper-small"
        self.offline_only = config.getboolean("MENU_BAR", "offline_mode", fallback=self.offline_only)
        self.overlay_enabled = config.getboolean("MENU_BAR", "show_subtitles", fallback=self.overlay_enabled)

    def save_preferences(self):
        config = read_config()
        if "DEVICE" not in config:
            config["DEVICE"] = {}
        if "LANGUAGE" not in config:
            config["LANGUAGE"] = {}
        if "MENU_BAR" not in config:
            config["MENU_BAR"] = {}
        if self.device_name:
            config["DEVICE"]["name"] = self.device_name
        config["LANGUAGE"]["source"] = language_by_name(self.source_name)[2]
        config["LANGUAGE"]["target"] = language_by_name(self.target_name)[2]
        config["LANGUAGE"]["whisper_model"] = self.whisper_model
        config["MENU_BAR"]["offline_mode"] = "1" if self.offline_only else "0"
        config["MENU_BAR"]["show_subtitles"] = "1" if self.overlay_enabled else "0"
        write_config(config)

    def refresh_devices(self):
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="macOS does not support loopback recording functionality")
                import soundcard as sc

                self.devices = sc.all_microphones(include_loopback=True)
            self.device_load_error = None
        except Exception as exc:
            self.devices = []
            self.device_load_error = str(exc)
            return

        names = [getattr(device, "name", "") for device in self.devices]
        if self.device_name in names:
            return
        preferred = None
        for device in self.devices:
            if is_desktop_audio_device(device):
                preferred = device
                break
        if preferred is None and self.devices:
            preferred = self.devices[0]
        if preferred is not None:
            self.device_name = getattr(preferred, "name", "")
            self.save_preferences()

    def rebuild_setting_controls(self):
        self.rebuild_device_popup()
        self.rebuild_language_popup(self.source_popup, self.source_name)
        self.rebuild_language_popup(self.target_popup, self.target_name)
        self.rebuild_whisper_popup()
        self.refresh_panel_state(check_login=False)

    def popup_remove_all(self, popup):
        if popup is not None:
            popup.removeAllItems()

    def rebuild_device_popup(self):
        if self.device_popup is None:
            return
        self.device_popup.removeAllItems()
        if self.device_load_error:
            self.device_popup.addItemWithTitle_(f"Device error")
            self.device_popup.setEnabled_(False)
            return
        if not self.devices:
            self.device_popup.addItemWithTitle_("No devices found")
            self.device_popup.setEnabled_(False)
            return
        for device in self.devices:
            name = getattr(device, "name", "")
            title = f"{name} [{device_type_label(device)}]"
            self.device_popup.addItemWithTitle_(title)
            self.device_popup.lastItem().setRepresentedObject_(name)
            if name == self.device_name:
                self.device_popup.selectItem_(self.device_popup.lastItem())

    def rebuild_language_popup(self, popup, selected_name):
        if popup is None:
            return
        popup.removeAllItems()
        for name, _bcp47, _iso639 in LANGUAGES:
            popup.addItemWithTitle_(name)
        popup.selectItemWithTitle_(selected_name)

    def rebuild_whisper_popup(self):
        if self.whisper_popup is None:
            return
        self.whisper_popup.removeAllItems()
        for model_name in WHISPER_MODELS:
            self.whisper_popup.addItemWithTitle_(model_name)
        self.whisper_popup.selectItemWithTitle_(self.whisper_model)

    def selectDevicePopup_(self, sender):
        selected_item = sender.selectedItem()
        if selected_item is not None and selected_item.representedObject() is not None:
            self.device_name = str(selected_item.representedObject())
            self.save_preferences()

    def refreshDevices_(self, _sender):
        self.refresh_devices()
        self.rebuild_setting_controls()

    def selectSourcePopup_(self, sender):
        self.source_name = str(sender.titleOfSelectedItem())
        self.save_preferences()
        self.rebuild_setting_controls()

    def selectTargetPopup_(self, sender):
        self.target_name = str(sender.titleOfSelectedItem())
        self.save_preferences()
        self.rebuild_setting_controls()

    def selectWhisperPopup_(self, sender):
        self.whisper_model = str(sender.titleOfSelectedItem())
        self.save_preferences()
        self.rebuild_setting_controls()

    def toggleOffline_(self, _sender):
        self.offline_only = not self.offline_only
        self.save_preferences()
        self.refresh_panel_state(check_login=False)

    def load_runtime(self):
        if self.runtime is not None:
            return self.runtime
        ensure_support_files()
        os.environ["DAT_APP_SUPPORT_DIR"] = str(APP_SUPPORT_DIR)
        os.environ["DAT_DISABLE_KEYBOARD"] = "1"
        if str(SOURCE_DIR) not in sys.path:
            sys.path.insert(0, str(SOURCE_DIR))
        import main as runtime

        failure_message = runtime.dependency_failure_message()
        if failure_message:
            raise RuntimeError(failure_message)
        runtime.require_dependencies()
        self.runtime = runtime
        return runtime

    def selected_device(self):
        self.refresh_devices()
        for device in self.devices:
            if getattr(device, "name", "") == self.device_name:
                return device
        if self.devices:
            return self.devices[0]
        return None

    def startTranslation_(self, _sender):
        if self.running() or self.busy():
            return
        if language_by_name(self.source_name)[2] == language_by_name(self.target_name)[2]:
            show_dialog("Source and target languages must be different.")
            return
        selected = self.selected_device()
        if selected is None:
            show_dialog("No audio device is available. Check Microphone permission and install BlackHole if needed.")
            return

        self.device_name = getattr(selected, "name", "")
        self.save_preferences()
        self.starting = True
        self.set_status("Loading models...")
        self.append_log(f"Device: {self.device_name}")
        self.append_log(f"Speech: {self.source_name} -> Translate to: {self.target_name}")
        self.append_log(f"Models: {self.whisper_model} + {translation_model_for(language_by_name(self.source_name)[2], language_by_name(self.target_name)[2])}")
        self.append_log("Loading translation models...")
        self.subtitle_overlay.set_text("Loading translation models...")
        threading.Thread(target=self.start_worker, args=(selected,), daemon=True).start()

    def start_worker(self, selected):
        try:
            runtime = self.load_runtime()
            source_name, source_bcp47, source_iso = language_by_name(self.source_name)
            _target_name, _target_bcp47, target_iso = language_by_name(self.target_name)
            translation_model = translation_model_for(source_iso, target_iso)

            if self.offline_only:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                os.environ["OFFLINE_ONLY"] = "1"
            else:
                os.environ.pop("HF_HUB_OFFLINE", None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                os.environ["OFFLINE_ONLY"] = "0"
            os.environ["WHISPER_MODEL"] = self.whisper_model

            transcriber = runtime.ArabicAudioTranscriber(
                selected_device=selected,
                on_event=self.on_transcriber_event,
                interactive=False,
                asr_language=source_bcp47,
                translation_model=translation_model,
            )
            with self.lock:
                self.transcriber = transcriber
                self.starting = False
            transcriber.start_background(enable_keyboard_shortcuts=False)
            AppHelper.callAfter(self.set_status, "Running")
            AppHelper.callAfter(self.append_log, "Translation running. You can close this panel; subtitles will continue.")
            AppHelper.callAfter(self.subtitle_overlay.set_text, f"Listening: {source_name}")
        except BaseException as exc:
            with self.lock:
                self.transcriber = None
                self.starting = False
            AppHelper.callAfter(self.set_status, "Start failed")
            AppHelper.callAfter(self.append_log, f"Failed to start: {exc}")
            AppHelper.callAfter(show_dialog, f"Failed to start translation:\n{exc}")

    def stopTranslation_(self, _sender):
        if not self.running() or self.stopping:
            return
        self.stopping = True
        self.set_status("Stopping...")
        self.append_log("Stopping translation...")
        threading.Thread(target=self.stop_worker, daemon=True).start()

    def stop_worker(self):
        transcriber = self.transcriber
        try:
            if transcriber is not None:
                transcriber.stop_background()
                transcriber.join_background()
                transcriber.save_transcript()
        finally:
            with self.lock:
                self.transcriber = None
                self.stopping = False
            AppHelper.callAfter(self.set_status, "Ready")
            AppHelper.callAfter(self.append_log, "Translation stopped.")
            AppHelper.callAfter(self.subtitle_overlay.set_text, "Translation stopped")

    def downloadModels_(self, _sender):
        if self.busy() or self.running():
            return
        if language_by_name(self.source_name)[2] == language_by_name(self.target_name)[2]:
            show_dialog("Source and target languages must be different.")
            return
        self.downloading = True
        self.set_status("Downloading models...")
        self.append_log("Downloading selected models...")
        threading.Thread(target=self.download_worker, daemon=True).start()

    def download_worker(self):
        try:
            runtime = self.load_runtime()
            from transformers import pipeline

            _source_name, _source_bcp47, source_iso = language_by_name(self.source_name)
            _target_name, _target_bcp47, target_iso = language_by_name(self.target_name)
            translation_model = translation_model_for(source_iso, target_iso)
            torch_device, _torch_dtype, _torch_runtime = runtime.select_torch_runtime()
            pipeline("automatic-speech-recognition", model=self.whisper_model, device=torch_device)
            pipeline("translation", model=translation_model, device=torch_device)
            AppHelper.callAfter(self.set_status, "Downloaded")
            AppHelper.callAfter(self.append_log, f"Downloaded: {self.whisper_model} + {translation_model}")
            AppHelper.callAfter(self.subtitle_overlay.set_text, "Models downloaded")
        except Exception as exc:
            AppHelper.callAfter(self.set_status, "Download failed")
            AppHelper.callAfter(self.append_log, f"Download failed: {exc}")
            AppHelper.callAfter(show_dialog, f"Model download failed:\n{exc}")
        finally:
            self.downloading = False
            AppHelper.callAfter(self.refresh_panel_state, False)

    def on_transcriber_event(self, event_type, payload=None):
        if event_type == "status":
            labels = {
                "transcribing": "Transcribing...",
                "translating": "Translating...",
            }
            AppHelper.callAfter(self.set_status, labels.get(str(payload), str(payload)))
        elif event_type == "log":
            AppHelper.callAfter(self.append_log, str(payload))
        elif event_type == "transcript":
            try:
                text = payload.get("english_text") or payload.get("arabic_text") or ""
                source_text = payload.get("arabic_text") or ""
                target_text = payload.get("english_text") or ""
            except Exception:
                text = ""
                source_text = ""
                target_text = ""
            if text:
                if source_text:
                    AppHelper.callAfter(self.append_log, f"Source: {source_text}")
                if target_text:
                    AppHelper.callAfter(self.append_log, f"Target: {target_text}")
                AppHelper.callAfter(self.append_log, "-" * 40)
                AppHelper.callAfter(self.subtitle_overlay.set_text, text)
                AppHelper.callAfter(self.set_status, "Running")
        elif event_type == "english":
            AppHelper.callAfter(self.subtitle_overlay.set_text, str(payload))
        elif event_type == "no_audio":
            try:
                device_name = payload.get("device_name") or "selected device"
                hint = payload.get("hint") or ""
            except Exception:
                device_name = "selected device"
                hint = ""
            message = f"No audio from {device_name}. Route YouTube/system output to BlackHole or a Multi-Output Device."
            AppHelper.callAfter(self.set_status, "Silent")
            AppHelper.callAfter(self.append_log, message)
            if hint:
                AppHelper.callAfter(self.append_log, hint)
            AppHelper.callAfter(self.subtitle_overlay.set_text, message)
        elif event_type == "audio_detected":
            AppHelper.callAfter(self.set_status, "Listening")
            AppHelper.callAfter(self.append_log, "Audio detected. Listening for speech...")
            AppHelper.callAfter(self.subtitle_overlay.set_text, "Audio detected. Listening for speech...")
        elif event_type == "no_speech":
            message = str(payload)
            AppHelper.callAfter(self.set_status, "Listening")
            AppHelper.callAfter(self.append_log, message)
            AppHelper.callAfter(self.subtitle_overlay.set_text, message)
        elif event_type == "error":
            AppHelper.callAfter(self.set_status, "Error")
            AppHelper.callAfter(self.append_log, f"Error: {payload}")
            AppHelper.callAfter(self.subtitle_overlay.set_text, f"Error: {payload}")

    def toggleOverlay_(self, _sender):
        self.overlay_enabled = not self.overlay_enabled
        if self.overlay_enabled:
            self.subtitle_overlay.show()
        else:
            self.subtitle_overlay.hide()
        self.save_preferences()
        self.refresh_panel_state(check_login=False)

    def clearOverlay_(self, _sender):
        self.subtitle_overlay.clear()

    def openCompactWindow_(self, _sender):
        if self.gui_process is not None and self.gui_process.poll() is None:
            self.activate_python_app()
            return
        ensure_support_files()
        env = os.environ.copy()
        env["DAT_APP_SUPPORT_DIR"] = str(APP_SUPPORT_DIR)
        env["DAT_APP_BUNDLE"] = str(APP_BUNDLE)
        env["DAT_MENU_BAR_PARENT_PID"] = str(os.getpid())
        env["DAT_SETTINGS_COLLAPSED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(SOURCE_DIR)
        log_path = LOG_DIR / "translator-window.log"
        log_file = open(log_path, "a", encoding="utf-8")
        self.gui_process = subprocess.Popen(
            [sys.executable, str(SOURCE_DIR / "gui.py")],
            cwd=str(SOURCE_DIR),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        self.refresh_panel_state(check_login=False)
        self.activate_python_app()

    def closeCompactWindow_(self, _sender):
        if self.gui_process is None or self.gui_process.poll() is not None:
            self.refresh_panel_state(check_login=False)
            return
        self.gui_process.terminate()
        try:
            self.gui_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.gui_process.kill()
        self.refresh_panel_state(check_login=False)

    def toggleOpenAtLogin_(self, _sender):
        target = not login_item_enabled()
        result = set_login_item_enabled(target)
        if result.returncode != 0:
            message = result.stderr.strip() or "Unable to update Login Items."
            show_dialog(message)
        self.refresh_panel_state()

    def quitApp_(self, _sender):
        if self.running():
            self.stop_worker()
        self.closeCompactWindow_(None)
        NSApplication.sharedApplication().terminate_(self)

    def activate_python_app(self):
        run_osascript(['tell application "Python" to activate'])


def main():
    app = NSApplication.sharedApplication()
    controller = MenuBarController.alloc().init()
    globals()["_controller"] = controller
    if os.environ.get("DAT_SHOW_PANEL_ON_LAUNCH", "0").strip() == "1":
        AppHelper.callAfter(controller.togglePanel_, None)
    app.run()


if __name__ == "__main__":
    main()
