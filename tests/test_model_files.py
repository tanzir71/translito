import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engines.model_files import (Ready, Missing, Incomplete, Corrupt, ModelNotReady,
                                Unavailable, inspect_model, whisper_spec, model_hint, ready_whisper)


def snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSLITO_WHISPER_MODEL_DIR", str(tmp_path / "not-installed"))
    folder = tmp_path / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo" / "snapshots" / "revision"
    folder.mkdir(parents=True)
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (folder / name).write_bytes(b"1234")
    return folder


def test_partial_snapshot_never_constructs_whisper_and_offers_resume(tmp_path, monkeypatch):
    import engines.model_files as files
    import faster_whisper
    from model_loading import ModelLoadManager
    folder = snapshot(tmp_path, monkeypatch)
    (folder / "model.bin").unlink()
    blobs = folder.parent.parent / "blobs"
    blobs.mkdir()
    (blobs / "weights.incomplete").write_bytes(b"0" * 42)
    spec = whisper_spec("openai/whisper-large-v3-turbo")
    status = inspect_model(spec, cache_roots=[tmp_path])
    assert status == Incomplete(42, 1620000000)
    monkeypatch.setattr(files, "inspect_model", lambda s: inspect_model(s, cache_roots=[tmp_path]))
    factory = Mock()
    monkeypatch.setattr(faster_whisper, "WhisperModel", factory)
    with pytest.raises(ModelNotReady):
        ModelLoadManager()._load_uncached(spec.key, "identity:en", -1, None, False, None)
    factory.assert_not_called()
    text, action = model_hint(spec, Incomplete(420000000, 1620000000), "Whisper Small")
    assert text == "Whisper Turbo isn't fully downloaded (0.42 of 1.62 GB). Sessions use Whisper Small until it finishes."
    assert action == "Resume download"


def test_manifest_sizes_and_legacy_files(tmp_path, monkeypatch):
    folder = snapshot(tmp_path, monkeypatch)
    spec = whisper_spec("openai/whisper-large-v3-turbo")
    assert isinstance(inspect_model(spec, cache_roots=[tmp_path]), Ready)
    (folder / "manifest.json").write_text(json.dumps({"files": [{"name": "model.bin", "size": 5}]}))
    assert inspect_model(spec, cache_roots=[tmp_path]) == Incomplete(4, 5)
    (folder / "model.bin").write_bytes(b"123456")
    status = inspect_model(spec, cache_roots=[tmp_path])
    assert isinstance(status, Corrupt)
    assert model_hint(spec, status)[1] == "Repair"
    (folder / "manifest.json").write_text("broken")
    assert isinstance(inspect_model(spec, cache_roots=[tmp_path]), Corrupt)


def test_downloaded_bytes_are_not_ready_until_verified(tmp_path,monkeypatch):
    folder=snapshot(tmp_path,monkeypatch)
    spec=whisper_spec("openai/whisper-large-v3-turbo")
    (folder/"manifest.json").write_text(json.dumps({"verified":False,"files":[{"name":"model.bin","size":4}]}))
    assert inspect_model(spec,cache_roots=[tmp_path])==Incomplete(4,4)


def test_missing_and_local_fallback_order(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSLITO_WHISPER_MODEL_DIR", str(tmp_path / "missing"))
    assert isinstance(inspect_model(whisper_spec("openai/whisper-small"), cache_roots=[tmp_path]), Missing)
    visited = []
    def inspect(spec):
        visited.append(spec.key)
        return Ready(tmp_path) if spec.key.endswith("base") else Missing()
    assert ready_whisper("openai/whisper-medium", inspect=inspect).endswith("base")
    assert visited == ["openai/whisper-medium", "openai/whisper-large-v3-turbo", "openai/whisper-small", "openai/whisper-base"]


def test_cloud_launch_does_not_preload_or_change_hf_flags(monkeypatch):
    import gui
    import os
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    fake = SimpleNamespace(preview_mode=False, transcriber=None, model_setup_busy=False,
        current_model_request=lambda: {"whisper_model": "openai/whisper-small"},
        engine_choice_var=SimpleNamespace(get=lambda: "cloud"),
        offline_only_var=SimpleNamespace(get=lambda: True))
    gui.TranslatorGUI.preload_current_models(fake)
    gui.TranslatorGUI.configure_offline_env(fake)
    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ
    monkeypatch.delenv("OFFLINE_ONLY", raising=False)


def test_access_failure_is_not_reported_as_corruption(tmp_path, monkeypatch):
    import engines.model_files as files
    from engines.model_library import ModelSpec
    spec = ModelSpec('model','Model','Speech','test/model','ct2',tmp_path)
    error = PermissionError('blocked')
    error.winerror = 448
    monkeypatch.setattr(files,'prepare_snapshot_cache',Mock(side_effect=error))
    status = inspect_model(spec)
    assert isinstance(status, Unavailable) and not isinstance(status, Corrupt)
    assert model_hint(spec,status)[1] == 'Repair cache'


def test_gguf_beside_repo_registry_is_not_a_corrupt_manifest(tmp_path):
    from engines.model_library import ModelSpec
    model = tmp_path/'translation.gguf';model.write_bytes(b'gguf-bytes')
    (tmp_path/'manifest.json').write_text(json.dumps({'other/repo':{'path':'elsewhere'}}))
    assert isinstance(inspect_model(ModelSpec('gguf','Translation','Translation','test/gguf','gguf',model,expected_size=10)),Ready)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows RedirectionGuard')
def test_inventory_inspection_repairs_protected_snapshot_links_offline(tmp_path):
    from pathlib import Path
    import subprocess,sys,hashlib
    repository = tmp_path/'models--test--inspection'
    folder = repository/'snapshots'/('a'*40);folder.mkdir(parents=True)
    blobs = repository/'blobs';blobs.mkdir()
    for name in ('config.json','tokenizer.json','model.bin'):
        data = name.encode();blob = blobs/hashlib.sha256(data).hexdigest();blob.write_bytes(data)
        (folder/name).symlink_to(Path('../../blobs')/blob.name)
    code = '''import ctypes,sys
from pathlib import Path
from ctypes import wintypes
from engines.model_files import inspect_model,Ready
from engines.model_library import ModelSpec,ModelLibrary
flags=wintypes.DWORD(1)
assert ctypes.WinDLL('kernel32').SetProcessMitigationPolicy(16,ctypes.byref(flags),ctypes.sizeof(flags))
folder=Path(sys.argv[1]);root=Path(sys.argv[2])
try: (folder/'model.bin').stat()
except OSError as error: assert error.winerror==448
else: raise AssertionError('Protection was not reproduced')
spec=ModelSpec('test','Test','Speech','test/inspection','ct2',folder)
assert isinstance(inspect_model(spec),Ready)
library=ModelLibrary(specs=[spec],models_root=root/'models',hub_roots=[root],protected_paths=[])
assert all(row.status=='Downloaded' for row in library.inventory())
assert all(not p.is_symlink() for p in folder.iterdir())
'''
    result = subprocess.run([sys.executable,'-c',code,str(folder),str(tmp_path)],capture_output=True,text=True,timeout=40)
    assert result.returncode == 0,result.stderr
