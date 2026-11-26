"""Small typed, save-on-change bindings; existing INI content is preserved."""
import math
from app_config import read_config, write_config, _ensure_section


# Every editable legacy variable, excluding transient status/progress values.
CONTROL_VARIABLES = (
    "mode", "listen_device", "listen_source_type", "speak_mic", "speak_output",
    "listen_source", "listen_target", "speak_source", "speak_target", "whisper",
    "quality", "conversation_other", "my_language", "audience_language", "both_languages",
    "keep_english", "same_language_speech", "one_way", "engine_profile", "offline_only",
    "monitor", "voice", "noise_gate", "chunk_duration", "transcript_folder",
)


class SettingsState:
    def __init__(self, path=None, *, writable=lambda: True):
        from settings_store import SettingsStore
        self.store = SettingsStore(path)
        self.path, self.writable = self.store.path, writable
        self.bindings, self.transient, self.errors = [], {}, {}

    def get(self, section, key, default):
        if (section, key) in self.transient:
            return self.transient[section, key]
        value = self.store.read().get(section, key, fallback=None, raw=True)
        if value is None:
            return default
        try:
            if isinstance(default, bool):
                if value.lower() not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
                    return default
                return value.lower() in {"1", "true", "yes", "on"}
            if isinstance(default, (int, float)):
                number = type(default)(value)
                return number if math.isfinite(number) else default
            return value
        except (TypeError, ValueError):
            return default

    def set(self, section, key, value, *, delay=0):
        from settings_schema import setting
        entry = setting(section, key, value)
        try:
            encoded = entry.encode(value)
        except (TypeError, ValueError):
            self.errors[section, key] = "Enter an amount like 5 or 12.50" if key.endswith("cap_usd") else "Enter a valid value"
            return False
        self.errors.pop((section, key), None)
        self.transient[section, key] = encoded if isinstance(value, str) else value
        if self.writable():
            self.store.update({(section, key): encoded}, delay=delay)
        return True

    def bind(self, var, section, key, default, *, encode=lambda v: v, decode=lambda v: v, writable=lambda: True):
        from settings_schema import setting
        var.set(decode(self.get(section, key, default)))
        var.setting = setting(section, key, default)
        var.settings_owner = getattr(self, "owner", None)
        var.validation_error = __import__("tkinter").StringVar(var._root)
        def changed(*_):
            if not writable():
                return
            try:
                value = encode(var.get())
                self.set(section, key, value, delay=.4 if isinstance(default, str) else 0)
                var.validation_error.set(self.errors.get((section, key), ""))
            except (ValueError, __import__("tkinter").TclError):
                var.validation_error.set("Enter a valid value")
        token = var.trace_add("write", changed)
        var.save_now = lambda: self.set(section, key, encode(var.get()))
        self.bindings.append((var, token))
        return var

    def bind_control(self, app, name):
        from settings_schema import CONTROL_SCHEMA
        entry = CONTROL_SCHEMA[name]
        var = getattr(app, name + "_var")
        encode, decode = lambda v: v, lambda v: v
        if name in {"listen_source", "listen_target", "speak_source", "speak_target", "conversation_other", "my_language", "audience_language"}:
            encode = lambda v: app.language_entry_by_name(v)[2]
            decode = app.language_name_for_iso
        elif name == "quality":
            encode, decode = str.lower, str.title
        elif name == "engine_profile":
            from gui import ENGINE_PROFILES
            encode = lambda v: ENGINE_PROFILES.get(v, "free")
            decode = lambda v: next((k for k,x in ENGINE_PROFILES.items() if x == v), "Free (recommended)")
        elif name == "same_language_speech":
            values = {"passthrough": "Pass my voice through", "voice": "Read it with the voice", "mute": "Mute"}
            encode = lambda v: next((k for k,x in values.items() if x == v), v)
            decode = lambda v: values.get(v, v)
        elif name in {"listen_device", "speak_mic", "speak_output"}:
            choices = {"listen_device": "listen_choices", "speak_mic": "speak_mic_choices", "speak_output": "output_choices"}[name]
            encode = lambda value: next((choice.name for choice in getattr(app, choices, ())
                                          if choice.display_name == value), value)
            decode = lambda value: next((choice.display_name for choice in getattr(app, choices, ())
                                          if choice.name == value), value)
        default = encode(var.get())
        return self.bind(var, entry.section, entry.key, default, encode=encode, decode=decode,
            writable=lambda: not getattr(app, "_restoring_devices", False) if name in {"listen_device", "speak_mic", "speak_output", "voice"} else True)

    def close(self):
        for var, token in self.bindings:
            var.trace_remove("write", token)
            var.save_now = lambda: None
            var.settings_owner = None
            var.validation_error = None
        self.bindings.clear()
        if self.writable():
            self.store.flush()
