"""Catalog contracts, legacy aliases and drift between app and site consumers."""
import ast
import json
from pathlib import Path

import pytest

from engines.languages import CATALOG, CODES, LATIN_CODES, PRIORITY, RTL_CODES, canonical_code, gui_entries, language, pair_default_variety

ROOT = Path(__file__).resolve().parents[1]


def test_priority_order_count_scripts_and_legacy_codes():
    assert [entry.code for entry in CATALOG] == ["en","de","es","fr","nl","nb","pl","pt","sv","ar","zh-Hans","zh-Hant","ja","ko","it","ru","tr","fa","ur"]
    assert len(CATALOG) == 19 and len({entry.base_code for entry in CATALOG}) == 18
    assert len(PRIORITY) == 14 and len(CODES) == 19
    assert {"ar","fa","ur"} == RTL_CODES
    assert {"nb","no","sv","nl","pl"} <= LATIN_CODES
    assert all(entry.code == canonical_code(entry.code) for entry in CATALOG)
    assert all(language(entry.bcp47) == entry for entry in CATALOG)


@pytest.mark.parametrize("raw,code", [("ar-AR","ar"),("es-ES","es"),("pt-PT","pt"),("no","nb"),("nob","nb"),("nor","nb"),("zh-CN","zh-Hans"),("zh-TW","zh-Hant"),("zho","zh-Hans"),("cmn","zh-Hans"),("jpn","ja"),("kor","ko")])
def test_existing_values_and_provider_aliases_map_without_changing_saved_codes(raw,code):
    assert canonical_code(raw) == code


def test_every_whole_catalog_consumer_and_site_export_use_the_same_source():
    import gui
    from engines import lid,mt_cloud
    from speech_output import _culture_for_language
    from tools.site_languages import serialized
    assert gui.LANGUAGES == gui_entries()
    assert lid.LATIN_LANGUAGES == LATIN_CODES
    assert mt_cloud.LANGUAGES == CODES
    assert gui.RTL_LANGUAGES == RTL_CODES
    assert all(_culture_for_language(entry.code) == entry.bcp47 for entry in CATALOG)
    assert (ROOT/"website/data/languages.json").read_text(encoding="utf-8") == serialized()
    data = json.loads(serialized())
    assert [row["code"] for row in data] == [entry.code for entry in CATALOG]
    assert sum(row["priority"] for row in data) == 14


def test_full_language_lists_cannot_be_reintroduced_in_consumers():
    for file in ("gui.py","engines/lid.py","engines/mt_cloud.py","speech_output.py","engines/checks.py"):
        tree = ast.parse((ROOT/file).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id in {"LANGUAGES","LATIN_LANGUAGES","RTL_LANGUAGES"} for target in node.targets):
                assert not any(isinstance(child,(ast.List,ast.Set,ast.Dict)) for child in ast.walk(node.value)), file


@pytest.mark.parametrize("source,target,variety",[("es","en","es-MX"),("en","es","es-MX"),("pt","en","pt-BR"),("en","pt","pt-BR"),("ar","en","")])
def test_default_variety_follows_the_selected_pair(source,target,variety):
    assert pair_default_variety(source,target) == variety
