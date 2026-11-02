import pytest

from app_config import load_conversation_config, migrate_conversation_config, read_config


@pytest.mark.parametrize("source,target,other,my,one_way", [
    ("ar", "en", "ar", "en", False), ("en", "ar", "ar", "ar", False),
    ("ar", "fa", "ar", "en", True), ("fr", "en", "fr", "en", False),
])
def test_old_pairs_migrate_additively(source, target, other, my, one_way, tmp_path):
    path = tmp_path / "config.ini"
    original = f"; keep this comment\r\n[LANGUAGE]\r\nsource = {source}\r\ntarget = {target}\r\nunknown = keep\r\n".encode()
    path.write_bytes(original)
    conversation = migrate_conversation_config(path)
    assert path.read_bytes().startswith(original)
    assert conversation.other_language == other
    assert conversation.my_language == my
    assert conversation.audience_language == other
    assert conversation.one_way == one_way
    assert read_config(path)["LANGUAGE"]["source"] == source
    assert read_config(path)["LANGUAGE"]["target"] == target
    first = path.read_bytes()
    migrate_conversation_config(path)
    assert path.read_bytes() == first


def test_partial_existing_conversation_and_bom_keep_every_old_byte(tmp_path):
    path = tmp_path / "config.ini"
    first = b"\xef\xbb\xbf[CONVERSATION]\r\nmy_language = ar\r\n; preserve comment\r\n"
    tail = b"[UNRELATED]\r\ncustom = keep\r\n"
    path.write_bytes(first + tail)
    conversation = migrate_conversation_config(path)
    assert conversation.my_language == "ar"
    assert path.read_bytes().startswith(first)
    assert path.read_bytes().endswith(tail)
    assert load_conversation_config(path).my_language == "ar"
    assert read_config(path)["UNRELATED"]["custom"] == "keep"


def test_settings_save_keeps_comments_formatting_unknown_keys_and_unchanged_bytes(tmp_path):
    from app_config import write_config
    path = tmp_path / "config.ini"
    original = b"\xef\xbb\xbf; owner comment\r\n[LANGUAGE]\r\nSOURCE: ar\r\ntarget = ar\r\n\r\n; preserve this\r\n[UNKNOWN]\r\ncustom  =  a value ; with semicolon\r\n"
    path.write_bytes(original)
    config = read_config(path)
    config["LANGUAGE"]["target"] = "en"
    write_config(config, path)
    assert path.read_bytes() == original.replace(b"target = ar", b"target = en")
    before = path.stat().st_mtime_ns
    write_config(read_config(path), path)
    assert path.stat().st_mtime_ns == before


def test_partial_settings_save_never_removes_unmentioned_data(tmp_path):
    import configparser
    from app_config import write_config
    path = tmp_path / "config.ini"
    original = b"[UNRELATED]\nvalue = keep\n; end\n"
    path.write_bytes(original)
    config = configparser.ConfigParser()
    config["ENGINES"] = {"profile": "offline"}
    write_config(config, path)
    assert path.read_bytes().startswith(original)
    assert read_config(path)["UNRELATED"]["value"] == "keep"
