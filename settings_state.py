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
        self.path, self.writable = path, writable
        self.bindings = []
        self.transient = {}

    def get(self, section, key, default):
        if (section, key) in self.transient:
            return self.transient[section, key]
        value = read_config(self.path).get(section, key, fallback=None, raw=True)
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

    def set(self, section, key, value):
        self.transient[section, key] = value
        if not self.writable():
            return
        config = read_config(self.path)
        encoded = str(int(value)) if isinstance(value, bool) else str(value)
        if config.get(section, key, fallback=None, raw=True) != encoded:
            _ensure_section(config, section)[key] = encoded
            write_config(config, self.path)

    def bind(self, var, section, key, default):
        var.set(self.get(section, key, default))
        token = var.trace_add("write", lambda *_: self.set(section, key, var.get()))
        self.bindings.append((var, token))
        return var

    def close(self):
        for var, token in self.bindings:
            var.trace_remove("write", token)
        self.bindings.clear()
