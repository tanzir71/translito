import configparser

import app_config
from app_config import (
    DEFAULT_HOTKEYS,
    load_hotkey_config,
    load_runtime_config,
    load_transcript_folder,
    save_hotkey_config,
    save_runtime_config,
    save_transcript_folder,
)
from device_utils import conference_mic_hint, is_virtual_device_name, normalize_device_name


def test_runtime_config_preserves_mac_visible_settings(tmp_path):
    config_path = tmp_path / "config.ini"
    save_runtime_config(
        config_path,
        mic_noise_gate=0,
        last_mode="speak",
        chunk_duration=9,
        offline_only=True,
    )

    loaded = load_runtime_config(config_path)

    assert loaded.mic_noise_gate == 0
    assert loaded.last_mode == "speak"
    assert loaded.chunk_duration == 9
    assert loaded.offline_only is True


def test_transcript_folder_round_trips(tmp_path):
    config_path = tmp_path / "config.ini"
    transcript_path = tmp_path / "My Transcripts"

    save_transcript_folder(transcript_path, config_path)

    assert load_transcript_folder(config_path) == transcript_path


def test_hotkey_config_uses_defaults_and_persists_overrides(tmp_path):
    config_path = tmp_path / "config.ini"

    assert load_hotkey_config(config_path) == DEFAULT_HOTKEYS

    updated = DEFAULT_HOTKEYS.copy()
    updated["toggle"] = "ctrl+shift+t"
    updated["stop"] = ""
    save_hotkey_config(config_path, updated)

    assert load_hotkey_config(config_path)["toggle"] == "ctrl+shift+t"
    assert load_hotkey_config(config_path)["stop"] == ""


def test_config_helpers_preserve_existing_sections(tmp_path):
    config_path = tmp_path / "config.ini"
    parser = configparser.ConfigParser()
    parser["DEVICE"] = {"name": "Existing Device"}
    with config_path.open("w") as handle:
        parser.write(handle)

    save_runtime_config(config_path, mic_noise_gate=0.004, last_mode="listen")

    loaded = configparser.ConfigParser()
    loaded.read(config_path)
    assert loaded["DEVICE"]["name"] == "Existing Device"
    assert loaded["RUNTIME"]["mic_noise_gate"] == "0.004"


def test_windows_config_path_uses_local_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "user-data"))

    assert app_config.default_config_path() == tmp_path / "user-data" / "Translito" / "config.ini"


def test_default_saves_migrate_legacy_settings_without_writing_to_working_folder(tmp_path, monkeypatch):
    legacy_dir = tmp_path / "installed-app"
    legacy_dir.mkdir()
    legacy = legacy_dir / "config.ini"
    original = "[DEVICE]\nname = Existing microphone\n[LANGUAGE]\nsource = fr\ntarget = en\n"
    legacy.write_text(original, encoding="utf-8")
    target = tmp_path / "user-data" / "Translito" / "config.ini"
    monkeypatch.setattr(app_config, "CONFIG_FILE", target)
    monkeypatch.setattr(app_config, "_legacy_config_paths", lambda: (legacy,))
    monkeypatch.chdir(legacy_dir)

    save_runtime_config(last_mode="speak")

    assert target.is_file()
    assert app_config.load_device_config() == "Existing microphone"
    assert app_config.load_language_config().source == "fr"
    assert load_runtime_config().last_mode == "speak"
    assert legacy.read_text(encoding="utf-8") == original


def test_user_settings_take_precedence_over_legacy_settings(tmp_path, monkeypatch):
    target = tmp_path / "user-data" / "Translito" / "config.ini"
    monkeypatch.setattr(app_config, "CONFIG_FILE", target)
    legacy = tmp_path / "config.ini"
    legacy.write_text("[DEVICE]\nname = Old microphone\n", encoding="utf-8")
    monkeypatch.setattr(app_config, "_legacy_config_paths", lambda: (legacy,))

    app_config.save_device_config("নতুন microphone")
    legacy.write_text("[DEVICE]\nname = Another old microphone\n", encoding="utf-8")

    assert app_config.load_device_config() == "নতুন microphone"
    assert not list(target.parent.glob("tmp*"))


def test_virtual_device_detection_includes_windows_cable_names():
    assert is_virtual_device_name("CABLE Input (VB-Audio Virtual Cable)")
    assert is_virtual_device_name("CABLE Output (VB-Audio Virtual Cable)")
    assert is_virtual_device_name("VoiceMeeter AUX Input")
    assert not is_virtual_device_name("Realtek USB Microphone")


def test_vb_cable_hint_never_tells_user_to_select_cable_input_as_mic():
    hint = conference_mic_hint("CABLE Input (VB-Audio Virtual Cable)")

    assert "CABLE Output (VB-Audio Virtual Cable)" in hint
    assert 'set the microphone to "CABLE Input' not in hint


def test_device_name_normalization_ignores_case_and_spacing():
    assert normalize_device_name("  Realtek  USB   Microphone ") == "realtek usb microphone"
