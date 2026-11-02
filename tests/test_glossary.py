import json

from engines.glossary import DEFAULT_TERMS, Glossary


def test_starter_merge_preserves_user_changes_and_disabled_terms(tmp_path):
    path = tmp_path / "glossary.json"
    original = {"version": 1, "custom_metadata": "keep", "terms": [
        {"english": "replica", "spellings": ["ربلكا"], "arabic_translation": "نسخة خاصة"},
        {"english": "meeting", "spellings": [], "disabled": True}]}
    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    glossary = Glossary(path)
    assert glossary.data["terms"][:2] == original["terms"]
    assert glossary.data["custom_metadata"] == "keep"
    assert len(glossary.data["terms"]) >= 150
    first_save = path.read_bytes()
    Glossary(path)
    assert path.read_bytes() == first_save
    assert "meeting" not in glossary.hotwords()


def test_back_transliteration_and_hotwords(tmp_path):
    glossary = Glossary(tmp_path / "glossary.json")
    restored, hits = glossary.restore_english("راجع ربليكا بعد الميتينج و ديبلوي")
    assert "replica" in restored and "deploy" in restored
    assert hits == 2
    assert "deployment" in glossary.hotwords() and "API" in glossary.hotwords()
    assert glossary.restore_english("هذه جملة عادية") == ("هذه جملة عادية", 0)


def test_invalid_glossary_is_preserved(tmp_path):
    import pytest
    path = tmp_path / "glossary.json"
    path.write_bytes(b"not valid json")
    with pytest.raises(ValueError):
        Glossary(path)
    assert path.read_bytes() == b"not valid json"


def test_read_only_glossary_merges_defaults_in_memory_without_writing(tmp_path):
    path = tmp_path / "absent.json"
    glossary = Glossary(path, read_only=True)
    assert len(glossary.terms) >= 150
    assert not path.exists()
