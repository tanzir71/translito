"""Language routing contracts use synthetic audio and wire messages only."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest

from engines.languages import CATALOG
from engines.language_support import provider_code
from engines.lid import PairLanguageDetector
from engines.mt_local import resolve_local_mt, UnsupportedPairError, TARGET_TOKENS
from engines.registry import provider_factories
from engines.streaming_protocols import ElevenLabsProtocol, SonioxProtocol, SpeechmaticsProtocol


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.code)
def test_registry_has_checked_capabilities_for_each_catalog_pair(entry):
    for factory in provider_factories():
        assert factory.language_checked_on == "2026-11-26"
        assert factory.language_evidence.startswith("https://")
        reason = factory.unavailable_reason(entry.code, "en")
        assert bool(reason) == (factory.name == "cohere-api" and entry.code not in {"ar", "en"})
        assert factory.unavailable_reason("zz", "en")


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.code)
def test_elevenlabs_wire_codes_and_language_metadata(entry):
    protocol = ElevenLabsProtocol(languages=("en", entry.code))
    query = parse_qs(urlsplit(protocol.endpoint).query)
    assert query["language_code"] == ["eng"]
    if entry.code != "en":
        assert query["secondary_languages"] == [entry.iso6393[0]]
    from engines.languages import canonical_code
    for iso in entry.iso6393:
        assert canonical_code(iso, preferred=entry.code) == entry.code


@pytest.mark.parametrize("code", ("nl", "nb", "pl", "sv", "zh-Hans", "zh-Hant", "ja", "ko"))
def test_every_new_local_direction_is_verified_or_explicitly_unavailable(code):
    manifest = json.loads(Path("engines/data/opus_pairs.json").read_text())
    unavailable = manifest["unavailable_standard_pairs"]
    for source, target in ((code, "en"), ("en", code)):
        entries = [e for e in manifest["pairs"] if (e["source"], e["target"]) == (source, target)]
        if entries:
            assert len(entries[0]["revision"]) == 40
            assert resolve_local_mt(source, target).repos == (entries[0]["repo"],)
        else:
            assert [source, target] in unavailable
            with pytest.raises(UnsupportedPairError, match="cloud translator"):
                resolve_local_mt(source, target)


def test_norwegian_and_chinese_acoustic_detection_preserve_user_choice():
    assert PairLanguageDetector(None, "nb").restrict({"no": .9, "en": .1}).language == "nb"
    assert PairLanguageDetector(None, "zh-Hant").restrict({"zh": .9, "en": .1}).language == "zh-Hant"
    assert provider_code("whisper", "nb") == "no"
    assert provider_code("google", "zh-Hant", target=True) == "zh-TW"
    assert provider_code("deepl", "zh-Hant", target=True) == "ZH-HANT"
    assert provider_code("deepl", "pt", target=True) == "PT-BR"
    assert TARGET_TOKENS["en", "zh-Hant"] == ">>cmn_Hant<<"
    assert TARGET_TOKENS["en", "zh-Hans"] == ">>cmn_Hans<<"


def test_streaming_contracts_do_not_use_arabic_pack_for_other_pairs():
    assert SpeechmaticsProtocol(languages=("en", "nl")).start()["transcription_config"]["language"] == "nl"
    assert SpeechmaticsProtocol(languages=("en", "zh-Hant")).start()["transcription_config"]["language"] == "cmn_en"
    assert SpeechmaticsProtocol(model="melia-1", languages=("en", "nb")).start()["transcription_config"]["language_hints"] == ["en", "no"]
    config = SonioxProtocol(other="zh-Hant", target="zh-Hant").start()
    assert config["translation"]["language_b"] == "zh"
    assert "Traditional" in config["context"]["general"][0]["value"]


def test_script_pair_preferences_survive_configparser_lowercase(tmp_path):
    from engines.settings import EngineSettings, save_engine_settings, load_engine_settings
    settings = EngineSettings(pair_overrides={"en_zh-Hant": {"mt_provider": "azure"}})
    path = tmp_path / "settings.ini"
    save_engine_settings(settings, path)
    assert load_engine_settings(path).resolve("en", "zh-Hant")["default_mt_provider"] == "azure"
