import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from engines.downloads import DownloadManager, DownloadJob


@pytest.fixture
def fake_job(tmp_path):
    fetcher = tmp_path / "fetcher.py"
    fetcher.write_text('''import time
def fetch(job, file, folder):
    path = folder / (file["name"] + ".incomplete")
    have = path.stat().st_size if path.exists() else 0
    with path.open("ab") as handle:
        while have < file["size"]:
            chunk = b"x" * min(256000, file["size"]-have)
            handle.write(chunk)
            handle.flush()
            have += len(chunk)
            time.sleep(.065)
    final = folder / file["name"]
    path.replace(final)
    return final
''')
    total = 20000000
    return DownloadJob("fake", "fake/model", "Fake model", str(tmp_path / "model"),
        files=[{"name": "model.bin", "size": total, "sha256": hashlib.sha256(b"x" * total).hexdigest()}],
        total=total, fetcher=str(fetcher))


def pump(manager, predicate, timeout=15, root=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if root:
            root.update()
        else:
            manager.poll()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError([(j.state, j.error, j.bytes) for j in manager.jobs])


def test_real_child_reports_progress_pause_resume_cancel_and_queue(tmp_path, fake_job):
    seen = []
    manager = DownloadManager(directory=tmp_path / "jobs", on_change=lambda j: seen.append(j.bytes) if j.id == "fake" else None)
    manager.enqueue(fake_job)
    pump(manager, lambda: fake_job.bytes > 1000000)
    manager.pause(fake_job)
    time.sleep(.15)
    partial = next(Path(fake_job.folder).glob("*.incomplete"))
    have = partial.stat().st_size
    assert have > 0 and fake_job.state == "Paused"
    manager.resume(fake_job)
    second = DownloadJob("second", "fake/second", "Second", str(tmp_path / "second"),
                         files=fake_job.files, fetcher=fake_job.fetcher)
    manager.enqueue(second)
    pump(manager, lambda: fake_job.state == "Ready")
    assert fake_job.bytes == fake_job.total
    assert all(a <= b for a,b in zip(seen, seen[1:])) and len(set(seen)) > 5
    assert second.state in {"Queued", "Downloading"}
    pump(manager, lambda: second.bytes > 0)
    manager.cancel(second)
    time.sleep(.15)
    assert second.state == "Cancelled"
    assert list(Path(second.folder).glob("*.incomplete"))
    manager.close()
    restarted = DownloadManager(directory=tmp_path / "jobs")
    assert next(j for j in restarted.jobs if j.id == second.id).state == "Cancelled"


def test_checksum_mismatch_never_publishes_ready_path(tmp_path, fake_job):
    fake_job.files[0]["size"] = 1000
    fake_job.files[0]["sha256"] = "0" * 64
    manager = DownloadManager(directory=tmp_path / "jobs")
    manager.enqueue(fake_job)
    pump(manager, lambda: fake_job.state == "Paused")
    assert "Checksum mismatch" in fake_job.error
    assert not fake_job.ready_path
    assert json.loads((Path(fake_job.folder) / "manifest.json").read_text())["corrupt"]
    manager.close()


def test_space_check_is_before_spawn_and_network_gate_is_independent(tmp_path, fake_job):
    manager = DownloadManager(directory=tmp_path, disk_usage=lambda p: SimpleNamespace(free=1))
    with pytest.raises(ValueError, match="Free at least"):
        manager.enqueue(fake_job)
    assert not manager.jobs and manager.process is None
    manager = DownloadManager(directory=tmp_path, blocked=lambda: True)
    with pytest.raises(ValueError, match="Internet is blocked"):
        manager.enqueue(fake_job)


def test_stall_retries_three_times_with_backoff(tmp_path, fake_job):
    now = [0]
    manager = DownloadManager(directory=tmp_path, clock=lambda: now[0])
    manager.jobs = [fake_job]
    fake_job.state = "Downloading"
    for attempt, delay in enumerate((10, 30, 60), 1):
        manager.active = fake_job
        manager._retry(fake_job)
        assert manager.retry_at == now[0] + delay
        assert fake_job.retries == attempt
        now[0] += delay
    manager.active = fake_job
    manager._retry(fake_job)
    assert fake_job.state == "Paused"
    assert fake_job.error == "Paused · check your connection"


def test_real_tk_heartbeat_during_five_second_child(tmp_path, fake_job, tk_parent):
    import tkinter as tk
    root = tk.Toplevel(tk_parent)
    root.withdraw()
    beats, progress = [], []
    def heartbeat():
        beats.append(time.monotonic())
        root.after(50, heartbeat)
    manager = DownloadManager(root, directory=tmp_path / "jobs", on_change=lambda j: progress.append(j.bytes))
    try:
        heartbeat()
        manager.enqueue(fake_job)
        pump(manager, lambda: fake_job.state == "Ready", root=root)
        assert max(b-a for a,b in zip(beats, beats[1:])) < .25
        assert len(set(progress)) > 5
        assert all(a <= b for a,b in zip(progress, progress[1:]))
    finally:
        manager.close()
        root.destroy()


def test_resume_uses_existing_hf_blob_cache(tmp_path,monkeypatch):
    import app_config
    import huggingface_hub.constants
    from engines.model_files import whisper_spec
    hub=tmp_path/"hub"
    folder=hub/"models--Systran--faster-whisper-small"/"snapshots"/"revision"
    folder.mkdir(parents=True)
    (folder/"config.json").write_text("{}")
    (folder/"tokenizer.json").write_text("{}")
    blobs=folder.parent.parent/"blobs"
    blobs.mkdir()
    (blobs/"weights.incomplete").write_bytes(b"x"*4096)
    monkeypatch.setattr(app_config,"CONFIG_FILE",tmp_path/"config.ini")
    monkeypatch.setattr(huggingface_hub.constants,"HF_HUB_CACHE",str(hub))
    manager=DownloadManager(directory=tmp_path/"jobs",disk_usage=lambda p:SimpleNamespace(free=10**10))
    job=manager.enqueue_model(whisper_spec("openai/whisper-small"))
    assert Path(job.folder)==folder and Path(job.cache_dir)==hub
    assert job.revision=="revision" and job.bytes==4096
    manager.close()


def test_windowed_frozen_child_can_write_json_to_inherited_pipe(monkeypatch):
    import ctypes
    import engines.downloads as downloads
    captured=[]
    def write(handle,buffer,length,written,overlap):
        assert handle==99
        captured.append(buffer.raw[:length])
        written._obj.value=length
        return True
    api=SimpleNamespace(GetStdHandle=lambda value:99,WriteFile=write)
    with monkeypatch.context() as context:
        context.setattr(downloads.sys,"stdout",None)
        downloads.write_json_line({"bytes":42,"total":100},kernel32=api)
    assert json.loads(captured[0])=={"bytes":42,"total":100}


def test_gemma_first_load_checks_template_before_publishing_ready(tmp_path, fake_job, monkeypatch):
    from dataclasses import asdict
    from engines import downloads, mt_translategemma as gemma
    import llama_cpp
    import psutil
    template = "{{ bos_token }}"
    size = 1000
    fake_job.gemma = True
    fake_job.repo = gemma.MANIFEST["repo"]
    fake_job.files = [{"name": gemma.MANIFEST["filename"], "size": size,
                       "sha256": hashlib.sha256(b"x" * size).hexdigest()}]
    closed, events = [], []
    def first_load(**kwargs):
        folder = Path(kwargs["model_path"]).parent
        assert not json.loads((folder / "manifest.json").read_text())["verified"]
        return SimpleNamespace(metadata={"tokenizer.chat_template": template}, close=lambda: closed.append(True))
    monkeypatch.setitem(gemma.MANIFEST, "bytes", size)
    monkeypatch.setitem(gemma.MANIFEST, "template_sha256", hashlib.sha256(template.encode()).hexdigest())
    monkeypatch.setattr(llama_cpp, "Llama", first_load)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(total=16 * 2**30))
    monkeypatch.setattr(downloads, "write_json_line", events.append)
    path = tmp_path / "job.json"
    path.write_text(json.dumps(asdict(fake_job)))
    assert downloads.download_child(path) == 0
    assert closed and events[-1]["ready"] == fake_job.folder
    assert json.loads((Path(fake_job.folder) / "manifest.json").read_text())["verified"]


def test_atomic_file_rename_cannot_move_visible_progress_backwards(tmp_path):
    seen = []
    manager = DownloadManager(directory=tmp_path / "jobs", on_change=lambda job: seen.append(job.bytes))
    job = DownloadJob("race", "fake/race", "Fake", str(tmp_path), total=100, bytes=80, state="Downloading")
    manager.active, manager.generation = job, "child"
    manager.last_progress = manager.clock()
    for count in (0, 90, 0, 100):
        manager.events.put(("child", {"bytes": count, "total": 100}))
    manager.poll()
    assert seen == [80, 90, 90, 100]
    manager.close()
