import configparser

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
