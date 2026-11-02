import configparser
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tempfile
import re

from engines.router import Conversation


def default_config_path():
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "Translito" / "config.ini"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Translito" / "config.ini"
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "translito" / "config.ini"


CONFIG_FILE = default_config_path()

DEFAULT_HOTKEYS = {
    "toggle": "ctrl+alt+t",
    "listen": "ctrl+alt+l",
    "speak": "ctrl+alt+s",
    "stop": "ctrl+alt+x",
}


@dataclass(frozen=True)
class RuntimeConfig:
    mic_noise_gate: float = 0.002
    last_mode: str = "listen"
    chunk_duration: float = 6.0
    offline_only: bool = False
    asr_preset: str = "balanced"


@dataclass(frozen=True)
class SpeakConfig:
    source: str = "en"
    target: str = "ar"
    mic_name: str = ""
    output_device_name: str = ""
    voice: str = "Automatic"
    monitor_spoken_audio: bool = False


@dataclass(frozen=True)
class LanguageConfig:
    source: str = "ar"
    target: str = "en"
    whisper_model: str = "openai/whisper-small"


@dataclass(frozen=True)
class ConversationConfig(Conversation):
    one_way: bool = False


def _path(path=None):
    return Path(path or CONFIG_FILE)


def _legacy_config_paths():
    # Installed copies used the executable folder; source runs used the current
    # folder. Read these only until the user's new settings file exists.
    app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return (app_dir / "config.ini", Path.cwd() / "config.ini")


def read_config(path=None):
    config = configparser.ConfigParser()
    config_path = _path(path)
    candidates = (config_path,)
    if config_path == CONFIG_FILE and not config_path.exists():
        candidates = _legacy_config_paths()
    for candidate in candidates:
        if config.read(candidate, encoding="utf-8-sig"):
            break
    return config


def write_config(config, path=None):
    config_path = _path(path)
    candidates = (config_path,) if config_path.exists() else (
        _legacy_config_paths() if config_path == CONFIG_FILE else ())
    original = next((candidate.read_bytes() for candidate in candidates if candidate.is_file()), b"")
    updated = original.decode("utf-8")
    old = configparser.ConfigParser()
    if original:
        old.read_string(original.decode("utf-8-sig"))
    newline = "\r\n" if "\r\n" in updated else "\n"
    sections = [(config.default_section, config.defaults()), *config._sections.items()]
    for section, values in sections:
        for key, value in values.items():
            value = str(value)
            if any(c in key + section for c in "\r\n") or any(c in value for c in "\r\n"):
                if old.has_option(section, key) and old.get(section, key, raw=True) == value:
                    continue
                raise ValueError("Multiline settings cannot be replaced; the existing config was preserved")
            if old.has_option(section, key) and old.get(section, key, raw=True) == value:
                continue
            headers = list(re.finditer(r"(?m)^(?:\ufeff)?\[([^\]\r\n]+)\][^\r\n]*(?:\r?\n|$)", updated))
            index = next((i for i, match in enumerate(headers) if match[1] == section), None)
            if index is None:
                if updated and not updated.endswith("\n"):
                    updated += newline
                updated += f"{newline}[{section}]{newline}{key} = {value}{newline}"
                continue
            start = headers[index].end()
            end = headers[index + 1].start() if index + 1 < len(headers) else len(updated)
            content = updated[start:end]
            option = re.search(r"(?im)^([ \t]*" + re.escape(key) + r"[ \t]*[=:][ \t]*)([^\r\n]*)(\r?\n|$)", content)
            if option is not None:
                if old.has_option(section, key) and "\n" in old.get(section, key, raw=True):
                    raise ValueError("Multiline settings cannot be replaced; the existing config was preserved")
                content = content[:option.start(2)] + value + content[option.end(2):]
            else:
                content += (newline if content and not content.endswith("\n") else "") + f"{key} = {value}{newline}"
            updated = updated[:start] + content + updated[end:]
    encoded = updated.encode("utf-8")
    if config_path.exists() and encoded == original:
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=config_path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(config_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _ensure_section(config, section):
    if section not in config:
        config[section] = {}
    return config[section]


def load_device_config(path=None):
    config = read_config(path)
    return config.get("DEVICE", "name", fallback=None)


def save_device_config(device_name, path=None):
    config = read_config(path)
    _ensure_section(config, "DEVICE")["name"] = device_name or ""
    write_config(config, path)


def load_language_config(path=None):
    config = read_config(path)
    return LanguageConfig(
        source=config.get("LANGUAGE", "source", fallback="ar"),
        target=config.get("LANGUAGE", "target", fallback="en"),
        whisper_model=config.get(
            "LANGUAGE", "whisper_model", fallback="openai/whisper-small"
        ),
    )


def save_language_config(source_code, target_code, whisper_model, path=None):
    config = read_config(path)
    section = _ensure_section(config, "LANGUAGE")
    section["source"] = source_code
    section["target"] = target_code
    section["whisper_model"] = whisper_model
    write_config(config, path)


def load_conversation_config(path=None):
    config = read_config(path)
    old = load_language_config(path)
    other = old.source if old.source != "en" else old.target
    other = other if other != "en" else "ar"
    section = config["CONVERSATION"] if "CONVERSATION" in config else {}
    other = section.get("other_language", other)
    if other == "en":
        other = "ar"
    pair = {"en", other}
    my_language = section.get("my_language", old.target if old.target in pair else "en")
    audience = section.get("audience_language", config.get("SPEAK", "speak_target", fallback=other))

    def boolean(key, default):
        return str(section.get(key, str(int(default)))).lower() in {"1", "true", "yes", "on"}

    speech = section.get("same_language_speech", "passthrough")
    return ConversationConfig(
        other_language=other,
        my_language=my_language if my_language in pair else "en",
        audience_language=audience if audience in pair else other,
        show_both=boolean("show_both", False),
        keep_english_terms=boolean("keep_english_terms", True),
        same_language_speech=speech if speech in {"passthrough", "voice", "mute"} else "passthrough",
        one_way=boolean("one_way", old.source != "en" and old.target != "en"),
    )


def migrate_conversation_config(path=None):
    """Append missing settings while retaining every original byte/key/comment.

    Unlike a normal user-requested settings update, migration never rewrites
    existing values or normalizes the old INI formatting.
    """
    from dataclasses import asdict
    config_path = _path(path)
    conversation = load_conversation_config(path)
    defaults = {key: str(int(value)) if isinstance(value, bool) else str(value)
                for key, value in asdict(conversation).items()}
    append_missing_settings("CONVERSATION", defaults, path)
    return conversation


def append_missing_settings(section, defaults, path=None):
    """Add migration defaults without rewriting any existing byte or value."""
    config_path = _path(path)
    existing = read_config(path)
    missing = {key: value for key, value in defaults.items()
               if not existing.has_option(section, key)}
    if not missing:
        return
    candidates = (config_path,) if config_path.exists() else (
        _legacy_config_paths() if config_path == CONFIG_FILE else ())
    original = next((p.read_bytes() for p in candidates if p.is_file()), b"")
    text = original.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    addition = "".join(f"{key} = {value}{newline}" for key, value in missing.items()).encode("utf-8")
    headers = list(re.finditer(rb"(?m)^(?:\xef\xbb\xbf)?\[([^\]\r\n]+)\][^\r\n]*(?:\r?\n|$)", original))
    section_index = next((i for i, match in enumerate(headers)
                          if match[1] == section.encode("utf-8")), None)
    if section_index is None:
        prefix = original + (newline.encode() if original and not original.endswith(b"\n") else b"")
        updated = prefix + f"{newline}[{section}]{newline}".encode() + addition
    else:
        end = headers[section_index + 1].start() if section_index + 1 < len(headers) else len(original)
        prefix = original[:end]
        if prefix and not prefix.endswith(b"\n"):
            prefix += newline.encode()
        updated = prefix + addition + original[end:]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=config_path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(config_path)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def save_conversation_config(conversation, path=None):
    from dataclasses import asdict
    config = read_config(path)
    section = _ensure_section(config, "CONVERSATION")
    for key, value in asdict(conversation).items():
        section[key] = str(int(value)) if isinstance(value, bool) else str(value)
    write_config(config, path)


def load_cohere_cache_dir(path=None):
    return read_config(path).get("ENGINES", "cohere_cache_dir", fallback="").strip() or None


def save_cohere_cache_dir(folder, path=None):
    folder = Path(folder).expanduser()
    if not folder.is_absolute():
        raise ValueError("Choose an absolute folder for the model cache")
    config = read_config(path)
    _ensure_section(config, "ENGINES")["cohere_cache_dir"] = str(folder)
    write_config(config, path)


def save_translategemma_path(model_path, path=None):
    model_path = Path(model_path).expanduser()
    if not model_path.is_absolute() or not model_path.is_file():
        raise ValueError("Choose an existing absolute path to the TranslateGemma model")
    config = read_config(path)
    _ensure_section(config, "ENGINES")["translategemma_path"] = str(model_path)
    write_config(config, path)


def load_runtime_config(path=None):
    config = read_config(path)
    section = config["RUNTIME"] if "RUNTIME" in config else {}
    try:
        gate = float(section.get("mic_noise_gate", "0.002"))
    except Exception:
        gate = 0.002
    last_mode = section.get("last_mode", "listen")
    if last_mode not in {"listen", "speak"}:
        last_mode = "listen"
    try:
        chunk_duration = min(15.0, max(3.0, float(section.get("chunk_duration", "6"))))
    except Exception:
        chunk_duration = 6.0
    offline_only = str(section.get("offline_only", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return RuntimeConfig(
        mic_noise_gate=gate,
        last_mode=last_mode,
        chunk_duration=chunk_duration,
        offline_only=offline_only,
        asr_preset=section.get("asr_preset", "balanced")
        if section.get("asr_preset", "balanced") in {"fast", "balanced", "best"} else "balanced",
    )


def save_runtime_config(
    path=None,
    mic_noise_gate=None,
    last_mode=None,
    chunk_duration=None,
    offline_only=None,
    asr_preset=None,
):
    config = read_config(path)
    section = _ensure_section(config, "RUNTIME")
    if mic_noise_gate is not None:
        section["mic_noise_gate"] = str(float(mic_noise_gate)).rstrip("0").rstrip(".")
        if section["mic_noise_gate"] == "-0":
            section["mic_noise_gate"] = "0"
    if last_mode is not None:
        section["last_mode"] = last_mode if last_mode in {"listen", "speak"} else "listen"
    if chunk_duration is not None:
        section["chunk_duration"] = str(min(15.0, max(3.0, float(chunk_duration)))).rstrip("0").rstrip(".")
    if offline_only is not None:
        section["offline_only"] = "1" if offline_only else "0"
    if asr_preset is not None:
        section["asr_preset"] = asr_preset if asr_preset in {"fast", "balanced", "best"} else "balanced"
    write_config(config, path)


def default_transcript_folder():
    return Path.home() / "Documents" / "Translito" / "Transcripts"


def load_transcript_folder(path=None):
    config = read_config(path)
    stored = config.get("TRANSCRIPTS", "folder", fallback="").strip()
    return Path(stored).expanduser() if stored else default_transcript_folder()


def save_transcript_folder(folder, path=None):
    config = read_config(path)
    _ensure_section(config, "TRANSCRIPTS")["folder"] = str(Path(folder).expanduser())
    write_config(config, path)


def load_speak_config(path=None):
    config = read_config(path)
    return SpeakConfig(
        source=config.get("SPEAK", "speak_source", fallback="en"),
        target=config.get("SPEAK", "speak_target", fallback="ar"),
        mic_name=config.get("SPEAK", "speak_mic_name", fallback=""),
        output_device_name=config.get("SPEAK", "speak_output_device_name", fallback=""),
        voice=config.get("SPEAK", "speak_voice", fallback="Automatic") or "Automatic",
        monitor_spoken_audio=config.getboolean(
            "SPEAK", "monitor_spoken_audio", fallback=False
        ),
    )


def save_speak_config(
    path=None,
    source=None,
    target=None,
    mic_name=None,
    output_device_name=None,
    voice=None,
    monitor_spoken_audio=None,
):
    config = read_config(path)
    section = _ensure_section(config, "SPEAK")
    if source is not None:
        section["speak_source"] = source
    if target is not None:
        section["speak_target"] = target
    if mic_name is not None:
        section["speak_mic_name"] = mic_name
    if output_device_name is not None:
        section["speak_output_device_name"] = output_device_name
    if voice is not None:
        section["speak_voice"] = voice or "Automatic"
    if monitor_spoken_audio is not None:
        section["monitor_spoken_audio"] = "1" if monitor_spoken_audio else "0"
    write_config(config, path)


def load_hotkey_config(path=None):
    config = read_config(path)
    if "HOTKEYS" not in config:
        return DEFAULT_HOTKEYS.copy()
    section = config["HOTKEYS"]
    result = {}
    for action, default in DEFAULT_HOTKEYS.items():
        result[action] = section[action] if action in section else default
    return result


def save_hotkey_config(path=None, hotkeys=None):
    config = read_config(path)
    section = _ensure_section(config, "HOTKEYS")
    for action, default in DEFAULT_HOTKEYS.items():
        value = (hotkeys or {}).get(action, default)
        section[action] = value or ""
    write_config(config, path)
