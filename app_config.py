import configparser
from dataclasses import dataclass
from pathlib import Path


CONFIG_FILE = "config.ini"

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


def _path(path=None):
    return Path(path or CONFIG_FILE)


def read_config(path=None):
    config = configparser.ConfigParser()
    config_path = _path(path)
    if config_path.exists():
        config.read(config_path)
    return config


def write_config(config, path=None):
    config_path = _path(path)
    with config_path.open("w") as handle:
        config.write(handle)


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
    )


def save_runtime_config(
    path=None,
    mic_noise_gate=None,
    last_mode=None,
    chunk_duration=None,
    offline_only=None,
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
