from types import SimpleNamespace
from unittest.mock import Mock
import sys

import numpy as np
import pytest

from engines.languages import CATALOG
from speech_output import LocalSpeechSynthesizer, MissingWindowsVoiceError, voice_matches_language, windows_voice_hint


@pytest.mark.parametrize("entry", CATALOG, ids=lambda entry: entry.code)
def test_windows_voice_lists_are_filtered_per_catalog_language(entry, monkeypatch, tmp_path):
    voices = [SimpleNamespace(name=item.code, id="voice-" + item.code, languages=[item.bcp47]) for item in CATALOG]
    engine = SimpleNamespace(getProperty=lambda _: voices, stop=Mock())
    monkeypatch.setitem(sys.modules, "pyttsx3", SimpleNamespace(init=lambda: engine))
    found = LocalSpeechSynthesizer(tmp_path).available_voices(entry.code)
    assert found == ["Automatic", entry.code]
    assert not windows_voice_hint(entry.code, found)


def test_voice_language_metadata_accepts_legacy_lcid_bytes_and_norwegian_alias():
    assert voice_matches_language(SimpleNamespace(languages=[b"\x05ja-JP"]), "ja")
    assert voice_matches_language(SimpleNamespace(languages=["411"]), "ja")
    assert voice_matches_language(SimpleNamespace(languages=["no-NO"]), "nb")
    assert not voice_matches_language(SimpleNamespace(languages=["zh-CN"]), "zh-Hant")


def test_missing_voice_hint_and_automatic_synthesis_never_choose_english(monkeypatch, tmp_path):
    voice = SimpleNamespace(name="English", id="en", languages=["en-US"])
    engine = SimpleNamespace(getProperty=lambda _: [voice], stop=Mock(), setProperty=Mock(), save_to_file=Mock())
    monkeypatch.setitem(sys.modules, "pyttsx3", SimpleNamespace(init=lambda: engine))
    synth = LocalSpeechSynthesizer(tmp_path)
    assert synth.available_voices("ko") == ["Automatic"]
    assert windows_voice_hint("ko", ["Automatic"]) == "No Windows voice for Korean. Add one in Windows speech settings."
    with pytest.raises(MissingWindowsVoiceError, match="No Windows voice for Korean"):
        synth._synthesize_with_pyttsx3("네", "Automatic", "ko")
    engine.setProperty.assert_not_called()
    engine.save_to_file.assert_not_called()


def test_automatic_and_explicit_synthesis_use_only_matching_voices(monkeypatch, tmp_path):
    voices = [SimpleNamespace(name="English", id="en", languages=["en-US"]),
              SimpleNamespace(name="Japanese 1", id="ja1", languages=["ja-JP"]),
              SimpleNamespace(name="Japanese 2", id="ja2", languages=["ja-JP"])]
    engine = SimpleNamespace(getProperty=lambda _: voices, stop=Mock(), setProperty=Mock(), save_to_file=Mock(), runAndWait=Mock())
    monkeypatch.setitem(sys.modules, "pyttsx3", SimpleNamespace(init=lambda: engine))
    monkeypatch.setattr("speech_output.read_wav_mono_float32", lambda _: (np.zeros(16), 16000))
    synth = LocalSpeechSynthesizer(tmp_path)
    for name, selected in (("Automatic", "ja1"), ("Japanese 2", "ja2"), ("English", "ja1")):
        synth._synthesize_with_pyttsx3("はい", name, "ja")
        engine.setProperty.assert_called_with("voice", selected)


def test_piper_never_falls_back_to_a_different_language(tmp_path):
    (tmp_path / "en_US-lessac-medium.onnx").touch()
    (tmp_path / "zh_CN-huayan-medium.onnx").touch()
    synth = LocalSpeechSynthesizer(tmp_path)
    assert not synth._piper_voice_paths("ja")
    assert not synth._piper_voice_paths("zh-Hant")
    assert synth._select_piper_voice("zh-Hans", "Automatic").name == "zh_CN-huayan-medium.onnx"


def test_outdated_voice_query_cannot_replace_the_current_audience():
    from gui import TranslatorGUI
    value = SimpleNamespace(_voice_generation=2, _voice_loading=True, voice_hint_var=Mock(), voice_var=Mock())
    TranslatorGUI._apply_voices(value, ["Automatic", "Old voice"], "en", 1)
    value.voice_var.set.assert_not_called()
    value.voice_hint_var.set.assert_not_called()
