import json
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engines.model_library import ModelLibrary, ModelLibraryError, ModelSpec
from model_loading import ModelLoadManager


@pytest.fixture
def library(tmp_path, monkeypatch):
    models, hub = tmp_path / "models", tmp_path / "hub"
    models.mkdir(); hub.mkdir()
    spec = ModelSpec("small", "Whisper small", "Speech", "example/whisper", "ct2", models / "small")
    lib = ModelLibrary(specs=[spec], models_root=models, hub_roots=[hub], protected_paths=[], manager=ModelLoadManager())
    monkeypatch.setattr(lib, "_release", lambda: None)
    return lib


def write_ct2(path):
    path.mkdir(parents=True, exist_ok=True)
    for filename in ("config.json", "tokenizer.json", "model.bin"):
        (path / filename).write_bytes(b"test-fixture")


def write_hub(root, repo="example/whisper", revision="a" * 40):
    path = root / ("models--" + repo.replace("/", "--"))
    snapshot = path / "snapshots" / revision
    write_ct2(snapshot)
    (path / "refs").mkdir()
    (path / "refs" / "main").write_text(revision)
    return path


def test_inventory_is_offline_and_distinguishes_available_partial_and_duplicate_copies(library, monkeypatch):
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "HfApi", lambda *a, **k: pytest.fail("Inventory used network"))
    before = library.inventory()[0]
    assert before.status == "Available" and before.size == 0
    folder = library.specs[0].local_path
    folder.mkdir(); (folder / "model.bin").write_bytes(b"partial")
    partial = library.inventory()[0]
    assert partial.status == "Partial" and partial.size == 7 and partial.deletable
    write_ct2(folder)
    write_hub(library.hub_roots[0])
    copies = library.inventory()
    assert len(copies) == 2 and all(row.status == "Downloaded" for row in copies)
    assert {row.storage for row in copies} == {"App cache", "Shared Hugging Face cache"}
    assert len({row.key for row in copies}) == 2


def test_delete_requires_confirmation_and_idle_state_before_any_change(library):
    write_ct2(library.specs[0].local_path)
    row = library.inventory()[0]
    with pytest.raises(ModelLibraryError, match="Confirm"):
        library.delete(row)
    library.session_active = lambda: True
    with pytest.raises(ModelLibraryError, match="Stop"):
        library.delete(row, confirmed=True)
    assert row.path.is_dir()
    library.session_active = lambda: False
    library.manager._loading_key = ("loading",)
    with pytest.raises(RuntimeError, match="Wait"):
        library.delete(row, confirmed=True)
    assert row.path.is_dir()


def test_delete_frees_only_selected_local_copy_and_offline_status_updates(library):
    local = library.specs[0].local_path
    write_ct2(local)
    shared = write_hub(library.hub_roots[0])
    row = next(r for r in library.inventory() if r.storage == "App cache")
    assert library.delete(row, confirmed=True) > 0
    assert not local.exists() and shared.exists()
    assert len(library.inventory()) == 1
    shared_row = library.inventory()[0]
    library.delete(shared_row, confirmed=True)
    assert library.inventory()[0].status == "Available"


def test_hub_delete_keeps_other_models_datasets_and_settings(library):
    root = library.hub_roots[0]
    target = write_hub(root)
    other = write_hub(root, "other/model", "b" * 40)
    dataset = root / "datasets--owner--clips"
    dataset.mkdir(); (dataset / "private.txt").write_text("preserve")
    settings = root.parent / "config.ini"
    settings.write_text("preserve")
    library.delete(library.inventory()[0], confirmed=True)
    assert not target.exists() and other.exists() and (dataset / "private.txt").read_text() == "preserve"
    assert settings.read_text() == "preserve"


def test_shared_revision_hash_cannot_expand_delete_to_another_model(library):
    root = library.hub_roots[0]
    target = write_hub(root)
    other = write_hub(root, "other/model")
    try:
        library.delete(library.inventory()[0], confirmed=True)
    except ModelLibraryError as error:
        assert "another model" in str(error) and target.exists()
    assert other.exists()


def test_partial_hub_download_can_be_removed(library):
    root = library.hub_roots[0]
    path = root / "models--example--whisper" / "blobs"
    path.mkdir(parents=True)
    (path / "download.incomplete").write_bytes(b"partial data")
    row = library.inventory()[0]
    assert row.status == "Partial" and row.size == 12
    library.delete(row, confirmed=True)
    assert not row.path.exists()


def test_external_folder_is_visible_but_never_recursively_deleted(library, tmp_path):
    external = tmp_path / "other-application"
    write_ct2(external)
    library.specs = (ModelSpec("external", "External", "Speech", "", "ct2", external),)
    row = library.inventory()[0]
    assert row.status == "Downloaded" and not row.deletable
    with pytest.raises(ModelLibraryError, match="external"):
        library.delete(row, confirmed=True)
    assert external.exists()


def test_protected_transcripts_and_linked_parent_are_rejected(library, monkeypatch):
    path = library.specs[0].local_path
    write_ct2(path)
    transcripts = path / "transcripts"
    transcripts.mkdir(); (transcripts / "saved.txt").write_text("keep")
    library.protected = (transcripts,)
    row = library.inventory()[0]
    with pytest.raises(ModelLibraryError, match="transcripts"):
        library.delete(row, confirmed=True)
    assert (transcripts / "saved.txt").read_text() == "keep"
    library.protected = ()
    import engines.model_library as module
    monkeypatch.setattr(module, "_linked", lambda candidate: candidate == library.models_root)
    with pytest.raises(ModelLibraryError, match="Linked"):
        library.delete(row, confirmed=True)
    assert path.exists()


def test_gemma_deletes_only_the_selected_file_or_its_partial_download(library, tmp_path):
    folder = tmp_path / "chosen-gguf"
    folder.mkdir()
    model = folder / "translator.gguf"
    model.write_bytes(b"weights")
    note = folder / "keep.txt"; note.write_text("keep")
    partial = folder / ".cache" / "huggingface" / "download" / "translator.gguf.hash.incomplete"
    partial.parent.mkdir(parents=True); partial.write_bytes(b"partial")
    unrelated = partial.with_name("other.gguf.hash.incomplete"); unrelated.write_bytes(b"keep")
    library.specs = (ModelSpec("gemma", "Gemma", "Translation", "repo/gemma", "gguf", model, "gemma"),)
    rows = library.inventory()
    assert len(rows) == 2 and {r.status for r in rows} == {"Partial", "Downloaded"}
    for row in rows:
        library.delete(row, confirmed=True)
    assert not model.exists() and not partial.exists() and note.exists() and unrelated.exists()


def test_missing_shards_are_partial_and_legacy_cached_models_are_visible(library):
    path = write_hub(library.hub_roots[0], "openai/whisper-medium")
    snapshot = next((path / "snapshots").iterdir())
    (snapshot / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"weight": "missing.safetensors"}}))
    row = next(r for r in library.inventory() if r.spec.repo == "openai/whisper-medium")
    assert row.status == "Partial" and row.deletable


def test_gemma_folder_named_like_a_model_is_never_deleted(library, tmp_path):
    folder = tmp_path / "private.gguf"
    folder.mkdir(); (folder / "notes.txt").write_text("keep")
    library.specs = (ModelSpec("gemma", "Gemma", "Translation", "repo/gemma", "gguf", folder, "gemma"),)
    row = library.inventory()[0]
    assert not row.deletable
    with pytest.raises(ModelLibraryError):
        library.delete(row, confirmed=True)
    assert (folder / "notes.txt").read_text() == "keep"


def test_refresh_picks_up_a_new_model_path_from_setup(library, tmp_path, monkeypatch):
    import engines.model_library as module
    chosen = [ModelSpec("gemma", "Gemma", "Translation", "owner/gemma", "gguf", tmp_path / "missing.gguf", "gemma")]
    monkeypatch.setattr(module, "default_catalog", lambda: tuple(chosen))
    library._default_specs = True
    assert library.inventory()[0].status == "Available"
    downloaded = tmp_path / "new-drive" / "model.gguf"
    downloaded.parent.mkdir(); downloaded.write_bytes(b"verified fixture")
    chosen[0] = ModelSpec("gemma", "Gemma", "Translation", "owner/gemma", "gguf", downloaded, "gemma")
    assert library.inventory()[0].path == downloaded and library.inventory()[0].status == "Downloaded"


def test_download_uses_anonymous_inference_files_and_obeys_offline_and_terms(library, monkeypatch):
    import huggingface_hub, model_loading
    metadata = Mock(return_value=SimpleNamespace(siblings=[SimpleNamespace(rfilename="model.safetensors"),
                                                           SimpleNamespace(rfilename="pytorch_model.bin")]))
    api = Mock(return_value=SimpleNamespace(model_info=metadata))
    monkeypatch.setattr(huggingface_hub, "HfApi", api)
    download = Mock(); monkeypatch.setattr(model_loading, "_download_repo_with_progress", download)
    row = library.inventory()[0]
    library.offline = lambda: True
    with pytest.raises(ModelLibraryError, match="Offline"):
        library.download(row)
    download.assert_not_called(); api.assert_not_called()
    library.offline = lambda: False
    library.download(row)
    assert download.call_args.kwargs["token"] is False
    assert download.call_args.kwargs["cache_dir"] == library.hub_roots[0]
    assert "model.bin" in download.call_args.kwargs["allow_patterns"]
    api.assert_called_once_with(token=False)
    library.specs = (ModelSpec("gated", "Gated", "Speech", "owner/gated", "transformers", setup="cohere"),)
    with pytest.raises(ModelLibraryError, match="terms"):
        library.download(library.inventory()[0])
    assert download.call_count == 1


def test_translation_download_prefers_one_weight_format_and_redacts_sdk_errors(library, monkeypatch):
    import huggingface_hub, model_loading
    library.specs = (ModelSpec("mt", "Translation", "Translation", "owner/translation", "transformers"),)
    monkeypatch.setattr(huggingface_hub, "HfApi", lambda **kw: SimpleNamespace(model_info=lambda *_:
        SimpleNamespace(siblings=[SimpleNamespace(rfilename="model.safetensors"), SimpleNamespace(rfilename="pytorch_model.bin")])))
    download = Mock(); monkeypatch.setattr(model_loading, "_download_repo_with_progress", download)
    row = library.inventory()[0]
    library.download(row)
    assert "*.safetensors" in download.call_args.kwargs["allow_patterns"]
    assert "pytorch_model*.bin" not in download.call_args.kwargs["allow_patterns"]
    download.side_effect = RuntimeError("SDK-secret-echo")
    with pytest.raises(ModelLibraryError) as error:
        library.download(row)
    assert "SDK-secret" not in str(error.value)


def test_maintenance_clears_cached_models_and_excludes_new_loads():
    manager = ModelLoadManager()
    manager._loaded = object()
    with pytest.raises(ValueError):
        with manager.maintenance():
            assert manager._loaded is None
            with pytest.raises(RuntimeError, match="managed"):
                manager.load_models("whisper", "translation")
            raise ValueError("operation failed")
    assert not manager._maintenance


def test_maintenance_refuses_an_inflight_load_and_then_becomes_available():
    manager = ModelLoadManager()
    started, finish = threading.Event(), threading.Event()
    def load(*args):
        started.set(); assert finish.wait(3)
        return SimpleNamespace(key=("model",))
    manager._load_uncached = load
    worker = threading.Thread(target=lambda: manager.load_models("model", "translation"))
    worker.start(); assert started.wait(1)
    try:
        with pytest.raises(RuntimeError, match="Wait"):
            with manager.maintenance():
                pytest.fail("Maintenance raced a model load")
    finally:
        finish.set(); worker.join(2)
    assert not worker.is_alive()
    with manager.maintenance():
        assert manager._loaded is None
