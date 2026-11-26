"""Canonical INI keys and the UI conversions used by settings bindings."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re


def money(value):
    text = str(value).strip().removeprefix("$").strip()
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        raise ValueError("Enter an amount like 5 or 12.50")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError("Enter an amount like 5 or 12.50") from None
    return f"{amount:.2f}"


@dataclass(frozen=True)
class Setting:
    section: str
    key: str
    type: type = str
    default: object = ""
    validator: object = None
    labels: dict = field(default_factory=dict)
    live: bool = False

    def encode(self, value):
        value = next((key for key, label in self.labels.items() if label == value), value)
        if self.validator:
            value = self.validator(value)
        if self.type is bool:
            value = str(value).lower() in {"1", "true", "yes", "on"}
            return str(int(value))
        if self.type in {int, float}:
            value = self.type(value)
        return str(value)


CONTROL_SCHEMA = {
    "mode": Setting("RUNTIME", "last_mode", default="listen"),
    "listen_device": Setting("DEVICE", "name"),
    "listen_source_type": Setting("CAPTURE", "source_type", default="Device"),
    "speak_mic": Setting("SPEAK", "mic_name"),
    "speak_output": Setting("SPEAK", "output_device_name"),
    "listen_source": Setting("LANGUAGE", "source", default="ar"),
    "listen_target": Setting("LANGUAGE", "target", default="en"),
    "speak_source": Setting("SPEAK", "speak_source", default="en"),
    "speak_target": Setting("SPEAK", "speak_target", default="ar"),
    "whisper": Setting("LANGUAGE", "whisper_model", default="openai/whisper-small"),
    "quality": Setting("RUNTIME", "asr_preset", default="balanced"),
    "conversation_other": Setting("CONVERSATION", "other_language", default="ar"),
    "my_language": Setting("CONVERSATION", "my_language", default="en"),
    "audience_language": Setting("CONVERSATION", "audience_language", default="ar"),
    "both_languages": Setting("CONVERSATION", "show_both", bool, False),
    "keep_english": Setting("CONVERSATION", "keep_english_terms", bool, True),
    "same_language_speech": Setting("CONVERSATION", "same_language_speech", default="passthrough"),
    "one_way": Setting("CONVERSATION", "one_way", bool, False),
    "engine_profile": Setting("ENGINES", "profile", default="free"),
    "offline_only": Setting("NETWORK", "block_all", bool, False),
    "monitor": Setting("SPEAK", "monitor_spoken_audio", bool, False),
    "voice": Setting("SPEAK", "voice", default="Automatic"),
    "noise_gate": Setting("RUNTIME", "mic_noise_gate", float, .002),
    "chunk_duration": Setting("RUNTIME", "chunk_duration", float, 6.),
    "transcript_folder": Setting("TRANSCRIPTS", "folder"),
}

SCHEMA = {(s.section, s.key): s for s in CONTROL_SCHEMA.values()}


def add(section, key, default, *, live=False, validator=None, labels=None):
    SCHEMA[section, key] = Setting(section, key, type(default), default, validator, labels or {}, live)


add("ENGINES", "monthly_cap_usd", "0.00", validator=money, live=True)
add("ENGINES", "engine_choice", "free")
add("ENGINES", "fallback_on_budget", "local", labels={"local": "Continue on this PC", "stop": "Stop the session"})
add("ENGINES", "budget_warn_percent", "80", labels={str(v): f"{v}%" for v in (50, 75, 80, 90, 100)})
add("UI", "engine_scope", "all", labels={"all": "All language pairs", "pair": "This language pair"})
for section, pairs in {
    "UI": {"subtitles_enabled": False, "reply_strip_visible": True, "last_settings_page": "Languages", "window_geometry": "800x640"},
    "LANGUAGE": {"english_passthrough": True, "variety": ""},
    "CAPTURE": {"default_app": "", "if_app_closed": "wait", "app_executable": "", "device_name": "", "default_app_prompted": False},
    "COSTGUARD": {"skip_non_speech": True, "skip_other_languages": True, "close_idle_seconds": "8"},
    "REPLIES": {"enabled": True, "trigger": "question", "show_native": False, "show_on_overlay": True},
    "SCHEDULE": {"enabled": False, "source": "weekly", "weekly_times": "[]", "lead_seconds": 60, "stop_rule": "end", "silence_seconds": 300,
                 "wait_for_app_audio": True, "ask_before_start": False, "only_with_call_link": False, "timezone": "UTC"},
    "SUBTITLES": {"show_when": "listening", "lines": 2, "text_size": 22, "background_alpha": .85, "show_original": False,
                  "click_through": True, "fade_seconds": 8, "hide_from_capture": True},
}.items():
    for key, default in pairs.items():
        add(section, key, default, live=section in {"UI", "SUBTITLES", "REPLIES"})
from app_config import DEFAULT_HOTKEYS
for key, value in DEFAULT_HOTKEYS.items():
    add("HOTKEYS", key, value, live=True)
for kind in ("asr", "mt"):
    for key in ("provider", "model"):
        add("ENGINES", f"default_{kind}_{key}", "")


def setting(section, key, default=""):
    if (section, key) in SCHEMA:
        return SCHEMA[section, key]
    if section == "ENGINES" and key.endswith("_monthly_cap_usd"):
        return Setting(section, key, default="", validator=lambda v: "" if not str(v).strip() else money(v))
    return Setting(section, key, type(default), default)
