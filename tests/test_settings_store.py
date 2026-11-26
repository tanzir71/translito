from dataclasses import replace
from pathlib import Path
import threading

import pytest

from app_config import read_config, write_config
from engines.settings import load_engine_settings, save_engine_settings
from settings_schema import money, CONTROL_SCHEMA
from settings_store import SettingsStore


@pytest.mark.parametrize("value,expected", [("5", "5.00"), ("5.5", "5.50"), ("$5", "5.00"), ("5.50", "5.50")])
def test_money_accepts_user_formats(value, expected):
    assert money(value) == expected


@pytest.mark.parametrize("value", ["", "-5", "NaN", "5.999", "five", "$", "Infinity"])
def test_invalid_money_is_rejected(value):
    with pytest.raises(ValueError, match="Enter an amount"):
        money(value)


def test_200_migration_moves_duplicate_values_then_removes_only_duplicates(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text("; keep\n[LANGUAGE]\nsource = ar\n[UI]\nlisten_source = French\noffline_only = 1\nwindow_geometry = 800x640\n[RUNTIME]\noffline_only = 1\n")
    store = SettingsStore(path)
    store.migrate(language_code=lambda value: "fr" if value == "French" else value)
    config = read_config(path)
    assert config["LANGUAGE"]["source"] == "fr"
    assert config["ENGINES"]["engine_choice"] == "local"
    assert config["NETWORK"]["block_all"] == "0"
    assert not config.has_option("UI", "listen_source")
    assert not config.has_option("RUNTIME", "offline_only")
    assert config["UI"]["window_geometry"] == "800x640"
    assert path.read_text().startswith("; keep\n")
    before = path.read_bytes()
    store.migrate()
    assert path.read_bytes() == before


def test_locked_writer_retries_five_times_reports_error_then_retry_succeeds(tmp_path):
    from app_config import _write_config
    locked, calls, sleeps = [True], [], []
    def writer(config, path):
        calls.append(1)
        if locked[0]:
            raise PermissionError("private path must not be shown")
        _write_config(config, path)
    store = SettingsStore(tmp_path / "config.ini", writer=writer, sleep=sleeps.append)
    store.update({("LANGUAGE", "source"): "es"}, sync=True)
    assert len(calls) == 6 and sleeps == [.1, .2, .4, .8, 1.6]
    assert store.error == "the settings file is locked"
    events = list(store.events.queue)
    assert events[-1] == ("error", "the settings file is locked")
    assert any(kind == "retrying" for kind, _ in events)
    locked[0] = False
    store.flush()
    assert not store.error
    assert read_config(store.path)["LANGUAGE"]["source"] == "es"
    assert list(store.events.queue)[-1][0] == "saved"


def test_stale_worker_cannot_undo_newer_ui_budget(tmp_path):
    path = tmp_path / "config.ini"
    save_engine_settings(load_engine_settings(path), path)
    old = load_engine_settings(path)
    store = SettingsStore(path)
    store.update({("ENGINES", "monthly_cap_usd"): "5.00"}, sync=True)
    def worker():
        providers = dict(old.providers)
        providers["soniox"] = replace(old.provider("soniox"), tested_signature="a" * 64)
        save_engine_settings(replace(old, providers=providers), path)
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    assert load_engine_settings(path).monthly_cap == 5
    assert load_engine_settings(path).provider("soniox").tested_signature == "a" * 64


def test_snapshot_delta_preserves_concurrent_sections(tmp_path):
    path = tmp_path / "config.ini"
    first, second = read_config(path), read_config(path)
    first["SCHEDULE"] = {"enabled": "1"}
    second["REPLIES"] = {"enabled": "0"}
    write_config(first, path)
    write_config(second, path)
    assert read_config(path)["SCHEDULE"]["enabled"] == "1"
    assert read_config(path)["REPLIES"]["enabled"] == "0"


def test_old_ui_engine_profile_wins_and_never_blocks_model_downloads(tmp_path):
    path=tmp_path/"config.ini"
    path.write_text("[UI]\nengine_profile = Custom\n[ENGINES]\nprofile = free\n")
    SettingsStore(path).migrate()
    settings=load_engine_settings(path)
    assert settings.engine_choice=="cloud" and settings.profile=="custom"
    assert not read_config(path).getboolean("NETWORK","block_all")
    assert not read_config(path).has_option("UI","engine_profile")


def test_legacy_speak_controls_migrate_to_the_runtime_keys(tmp_path):
    from app_config import load_speak_config
    path = tmp_path / "config.ini"
    path.write_text("[UI]\nspeak_mic = USB mic\nspeak_output = CABLE Input\nvoice = Spanish voice\n")
    SettingsStore(path).migrate()
    speak = load_speak_config(path)
    assert (speak.mic_name, speak.output_device_name, speak.voice) == ("USB mic", "CABLE Input", "Spanish voice")
