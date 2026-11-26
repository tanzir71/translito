import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest

from engines.checks import CheckSample, SampleCatalog
from engines.languages import language


MANIFEST = json.loads(Path("engines/data/check_samples.json").read_text(encoding="utf-8"))
NEW_CODES = ("nl", "nb", "pl", "sv", "zh-Hans", "zh-Hant", "ja", "ko", "es", "pt")


def fixture_catalog(code, *, corrupt=""):
    manifest = copy.deepcopy(MANIFEST)
    config = language(code).fleurs_config
    spec = manifest["fleurs"]["subsets"][config]
    audio = b"synthetic fixture audio"
    rows = []
    for clip in spec["clips"]:
        clip.update(bytes=len(audio), sha256=hashlib.sha256(audio).hexdigest())
        rows.append(dict(row_idx=clip["row_index"], row=dict(id=clip["clip_id"], transcription=clip["reference"],
            audio=[dict(src="https://datasets-server.huggingface.co/cached-assets/google/fleurs/--/" +
                manifest["fleurs"]["revision"] + "/--/" + config + "/clip.wav")])))
    if corrupt == "metadata":
        rows[0]["row"]["id"] = -1
    if corrupt == "revision":
        rows[0]["row"]["audio"][0]["src"] = "https://example.test/new-revision.wav"
    def fetch(url):
        if "/rows?" in url or "/filter?" in url:
            query = parse_qs(urlsplit(url).query)
            assert query["revision"] == [manifest["fleurs"]["revision"]]
            assert query["split"] == [spec["split"]]
            return json.dumps(dict(rows=rows)).encode()
        return audio + b"tampered" if corrupt == "audio" else audio
    catalog = SampleCatalog(fetch=fetch, manifest=manifest)
    catalog.recording = lambda data, source, target, **kw: CheckSample(np.zeros(16), 16000, source, target, **kw)
    return catalog


@pytest.mark.parametrize("code", NEW_CODES)
def test_pinned_public_loader_uses_catalog_config_revision_and_default_variety(code):
    subset = MANIFEST["fleurs"]["subsets"][language(code).fleurs_config]
    assert len(subset["clips"]) == 3
    for clip in subset["clips"]:
        assert len(clip["sha256"]) == 64
        assert clip["dataset_revision"] == MANIFEST["fleurs"]["revision"]
        assert clip["reference"] and clip["source_filename"].endswith(".wav")
        assert 0 < clip["bytes"] < 8 * 1024 * 1024
    samples = fixture_catalog(code).public(code, "en")
    assert len(samples) == 3
    assert all(s.reference and s.variety == language(code).default_variety for s in samples)
    if code.startswith("zh-"):
        assert all(s.reference_script == "Hans" and "Simplified" in s.label for s in samples)


@pytest.mark.parametrize("corrupt", ("metadata", "revision", "audio"))
def test_changed_public_samples_are_rejected_before_inference(corrupt):
    with pytest.raises(ValueError, match="Public sample"):
        fixture_catalog("nl", corrupt=corrupt).public("nl", "en")


def test_traditional_reuses_the_mandarin_pin_without_a_fabricated_reference():
    assert language("zh-Hans").fleurs_config == language("zh-Hant").fleurs_config
    hans = fixture_catalog("zh-Hans").public("zh-Hans", "en")
    hant = fixture_catalog("zh-Hant").public("zh-Hant", "en")
    assert [s.reference for s in hans] == [s.reference for s in hant]
