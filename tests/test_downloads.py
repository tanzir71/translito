import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from engines.downloads import DownloadManager, DownloadJob


@pytest.mark.parametrize("format", ["ct2", "transformers"])
def test_startup_adopts_complete_cache_instead_of_restoring_old_failure(tmp_path, format):
    from dataclasses import asdict
    folder = tmp_path / "cached"
    folder.mkdir()
    names = ("config.json", "model.bin", "tokenizer.json") if format == "ct2" else ("config.json", "pytorch_model.bin", "source.spm")
    for name in names:
        (folder / name).write_text("cached")
    queue = tmp_path / "queue"
    queue.mkdir()
    job = DownloadJob("old", "fake/cached", "Cached", str(folder), format=format,
                      state="Paused", pause_reason="failure", error="Old failed download", total=100)
    (queue / "old.json").write_text(json.dumps(asdict(job)))
    manager = DownloadManager(directory=queue, blocked=lambda: True)
    restored = manager.jobs[0]
    assert restored.state == "Ready" and restored.fraction == 1
    assert not restored.error and not restored.pause_reason
    assert restored.ready_path == str(folder) and manager.process is None
    assert json.loads((queue / "old.json").read_text())["state"] == "Ready"
    manager.close()


def test_unverified_complete_files_keep_explicit_pause(tmp_path):
    from dataclasses import asdict
    folder = tmp_path / "cached"
    folder.mkdir()
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (folder / name).write_text("cached")
    (folder / "manifest.json").write_text(json.dumps({"files": [], "verified": False}))
    queue = tmp_path / "queue"
    queue.mkdir()
    job = DownloadJob("partial", "fake/partial", "Partial", str(folder), state="Paused", pause_reason="user")
    (queue / "partial.json").write_text(json.dumps(asdict(job)))
    manager = DownloadManager(directory=queue)
    assert manager.jobs[0].state == "Paused"
    manager.close()


def test_external_cache_completion_reconciles_without_queuing_another_download(tmp_path):
    manager = DownloadManager(directory=tmp_path / "queue")
    folder = tmp_path / "cached"
    job = DownloadJob("external", "fake/external", "External", str(folder), state="Paused", pause_reason="failure", error="Old failure")
    manager.enqueue(job)
    folder.mkdir()
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (folder / name).write_text("cached")
    manager.reconcile_setup((), enabled=False)
    assert job.state == "Ready" and not job.error
    assert len(manager.jobs) == 1 and manager.process is None
    manager.close()


def test_metadata_write_failure_is_actionable_and_keeps_safe_diagnostics(tmp_path, fake_job, monkeypatch):
    from dataclasses import asdict
    from engines import downloads
    events = []
    monkeypatch.setattr(downloads, "write_json_line", events.append)
    def denied(*_):
        raise PermissionError(13, "signed-url-with-private-token")
    monkeypatch.setattr(downloads, "_write", denied)
    path = tmp_path / "job.json"
    path.write_text(json.dumps(asdict(fake_job)))
    assert downloads.download_child(path) == 1
    assert "Windows blocked access" in events[-1]["error"]
    assert events[-1]["error_code"] == "write_manifest:PermissionError:errno=13"
    assert "private-token" not in json.dumps(events)


def test_complete_cache_does_not_require_disk_space_probe(tmp_path, monkeypatch):
    from engines import downloads
    (tmp_path / "model.bin").write_bytes(b"cached")
    monkeypatch.setattr(downloads.shutil, "disk_usage", lambda _: (_ for _ in ()).throw(OSError(22, "bad volume query")))
    assert downloads._check_cached_files(tmp_path, [{"name": "model.bin", "size": 6}], "") == (6, False)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows RedirectionGuard')
def test_snapshot_is_readable_with_redirectionguard_enforced(tmp_path):
    import subprocess, sys
    repo = tmp_path / 'models--test--guard'
    folder = repo / 'snapshots' / ('a' * 40)
    folder.mkdir(parents=True)
    blob = repo / 'blobs' / ('b' * 64)
    blob.parent.mkdir()
    blob.write_bytes(b'model bytes')
    pointer = folder / 'model.bin'
    pointer.symlink_to(Path('../../blobs') / blob.name)
    code = '''import ctypes,sys
from pathlib import Path
from ctypes import wintypes
from engines.downloads import _file_size
api=ctypes.WinDLL('kernel32',use_last_error=True)
api.GetCurrentProcess.restype=ctypes.c_void_p
api.GetProcessMitigationPolicy.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t]
flags=wintypes.DWORD(1)
assert api.SetProcessMitigationPolicy(16,ctypes.byref(flags),ctypes.sizeof(flags))
p=Path(sys.argv[1])
try:
    p.stat()
except OSError as error:
    assert error.winerror == 448
else:
    raise AssertionError('Expected Windows to block the user-created link')
assert _file_size(p)==11 and not p.is_symlink()
assert api.GetProcessMitigationPolicy(api.GetCurrentProcess(),16,ctypes.byref(flags),ctypes.sizeof(flags))
assert flags.value & 1
'''
    result = subprocess.run([sys.executable, '-c', code, str(pointer)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert blob.read_bytes() == pointer.read_bytes() == b'model bytes'


def test_untrusted_mount_point_is_not_retried_forever():
    from engines.downloads import _setup_failure
    error = OSError(22, 'blocked link')
    error.winerror = 448
    result = _setup_failure(error, 'check_cache')
    assert not result.get('retryable') and 'Windows blocked a link' in result['error']


def test_transient_cache_failure_retries_before_pausing(tmp_path, fake_job, monkeypatch):
    from dataclasses import asdict
    from engines import downloads
    fake_job.files[0].update(size=1000, sha256=hashlib.sha256(b"x" * 1000).hexdigest())
    original = downloads._check_cached_files
    attempts, events = [], []
    def transient(*args):
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError(22, "temporary cache access")
        return original(*args)
    monkeypatch.setattr(downloads, "_check_cached_files", transient)
    monkeypatch.setattr(downloads, "write_json_line", events.append)
    monkeypatch.setattr(downloads.time, "sleep", lambda _: None)
    path = tmp_path / "retry.json"
    path.write_text(json.dumps(asdict(fake_job)))
    assert downloads.download_child(path) == 0
    assert len(attempts) == 3
    assert sum(event.get("stage") == "Checking cache" for event in events) == 2
    assert "ready" in events[-1]


def test_cache_error_retains_safe_windows_code():
    from engines.downloads import _setup_failure
    error = OSError(22, "private signed URL")
    error.winerror = 87
    error.cache_operation = "free_space"
    result = _setup_failure(error, "check_cache")
    assert result["error_code"] == "check_cache:OSError:free_space:errno=22:winerror=87"
    assert result["retryable"] and "private" not in json.dumps(result)


def test_cancel_stops_all_duplicate_attempts_and_clears_errors(tmp_path):
    manager = DownloadManager(directory=tmp_path / "jobs")
    first = DownloadJob("first", "fake/same", "First", str(tmp_path), state="Downloading", bytes=40, total=100, error="Old error", error_code="old")
    second = DownloadJob("second", "fake/same", "Second", str(tmp_path), state="Queued")
    ready = DownloadJob("ready", "fake/same", "Ready", str(tmp_path), state="Ready")
    manager.jobs, manager.active = [first, second, ready], first
    manager.cancel(first)
    assert manager.active is None
    assert first.state == second.state == "Cancelled" and ready.state == "Ready"
    assert first.bytes == 40 and not first.error and not first.error_code
    manager.close()


def test_cancel_while_worker_creation_is_pending_terminates_late_process(tmp_path):
    import threading
    from unittest.mock import Mock
    entered, release, terminated = threading.Event(), threading.Event(), threading.Event()
    child = Mock()
    child.terminate.side_effect = terminated.set
    def spawn(*args, **kwargs):
        entered.set()
        release.wait(2)
        return child
    root = SimpleNamespace(after=lambda *a: 'timer', after_cancel=lambda *a: None)
    manager = DownloadManager(root, directory=tmp_path/'jobs', spawn=spawn)
    job = DownloadJob('pending','fake/pending','Pending',str(tmp_path))
    manager.enqueue(job)
    manager.poll()
    assert entered.wait(1)
    manager.cancel(job)
    release.set()
    assert terminated.wait(2)
    assert manager.active is None and manager.process is None and job.state == 'Cancelled'
    child.terminate.assert_called_once()
    manager.close()


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


def pump(manager, predicate, timeout=30, root=None):
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
    assert seen == [100] and job.bytes == 100
    manager.close()


def test_next_file_returns_to_downloading_after_verifying_previous_file(tmp_path):
    manager = DownloadManager(directory=tmp_path / "jobs")
    job = DownloadJob("files", "fake/files", "Multiple files", str(tmp_path), total=1000, bytes=10, state="Verifying")
    manager.active, manager.generation = job, "child"
    manager.last_progress = manager.clock()
    manager.events.put(("child", {"file": "model.bin", "bytes": 20, "total": 1000}))
    manager.poll()
    assert job.state == "Downloading" and job.bytes == 20
    manager.close()


def test_verification_burst_persists_once_per_ui_frame(tmp_path, monkeypatch):
    from unittest.mock import Mock
    manager = DownloadManager(directory=tmp_path / 'jobs')
    job = DownloadJob('burst', 'fake/burst', 'Burst', str(tmp_path), state='Downloading')
    manager.active, manager.generation = job, 'child'
    saved, changed = Mock(), Mock()
    monkeypatch.setattr(manager, 'save', saved)
    manager.on_change = changed
    for _ in range(100):
        manager.events.put(('child', {'stage':'Verifying'}))
    manager.poll()
    assert job.state == 'Verifying'
    saved.assert_called_once_with(job)
    changed.assert_called_once_with(job)
    manager.close()


def test_resumed_worker_activity_below_saved_progress_does_not_look_stalled(tmp_path):
    now = [0]
    manager = DownloadManager(directory=tmp_path / "jobs", clock=lambda: now[0])
    job = DownloadJob("resume", "fake/resume", "Partial", str(tmp_path), total=100, bytes=80, state="Downloading")
    manager.jobs, manager.active, manager.generation = [job], job, "child"
    now[0] = 59
    manager.events.put(("child", {"file": "model.bin", "bytes": 20, "total": 100}))
    manager.poll()
    assert job.state == "Downloading" and job.bytes == 80
    now[0] = 110
    manager.events.put(("child", {"file": "model.bin", "bytes": 20, "total": 100}))
    manager.poll()
    assert job.state == "Downloading"
    now[0] = 120
    manager.poll()
    assert job.state == "Stalled · retrying"  # A repeated heartbeat is still idle.
    manager.close()


def test_buffered_sdk_reports_transfer_before_files_are_written(tmp_path, monkeypatch):
    """Xet can receive chunks for over a minute before flushing its first file."""
    from dataclasses import asdict
    from engines import downloads
    import huggingface_hub
    folder = tmp_path / "buffered"
    job = DownloadJob("buffered", "fake/buffered", "Buffered", str(folder), total=1000)
    files = [{"name": "model.bin", "size": 1000,
              "sha256": hashlib.sha256(b"x" * 1000).hexdigest()}]
    monkeypatch.setattr(downloads, "_plan", lambda *_: ("revision", files))
    emitted = []
    monkeypatch.setattr(downloads, "write_json_line",
        lambda data: emitted.append((dict(data), (folder / "model.bin").exists())))
    def buffered_fetch(repo, name, *, local_dir, tqdm_class, **kwargs):
        # Both SDK signals are cumulative views of the same bytes, not additive.
        with tqdm_class(total=1000) as bar:
            bar.update_transfer(400)
            time.sleep(.3)
            bar.update(400)
            bar.update_transfer(300)
            time.sleep(.3)
            path = Path(local_dir) / name
            path.write_bytes(b"x" * 1000)
            return path
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", buffered_fetch)
    path = tmp_path / "buffered.json"
    path.write_text(json.dumps(asdict(job)))
    assert downloads.download_child(path) == 0
    before_flush = [data["bytes"] for data, exists in emitted if not exists and "bytes" in data]
    assert 400 in before_flush and 700 in before_flush
    assert emitted[-1][0]["bytes"] == 1000 and "ready" in emitted[-1][0]


@pytest.mark.parametrize("status,retry", [(429, True), (503, True), (403, False), (404, False)])
def test_remote_failure_retries_transient_errors_without_exposing_sdk_details(tmp_path, monkeypatch, status, retry):
    from dataclasses import asdict
    from engines import downloads
    import httpx
    request = httpx.Request("GET", "https://example.test/model?token=private-test-token")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError("private-test-token", request=request, response=response)
    def fail(*_):
        raise error
    monkeypatch.setattr(downloads, "_plan", fail)
    events = []
    monkeypatch.setattr(downloads, "write_json_line", events.append)
    job = DownloadJob("error", "fake/error", "Failure", str(tmp_path / "model"), state="Downloading")
    path = tmp_path / "error.json"
    path.write_text(json.dumps(asdict(job)))
    assert downloads.download_child(path) == 1
    assert "private-test-token" not in json.dumps(events)
    assert bool(events[-1].get("retryable")) is retry
    manager = DownloadManager(directory=tmp_path / "queue", clock=lambda: 0)
    manager.jobs, manager.active, manager.generation = [job], job, "child"
    manager.events.put(("child", events[-1]))
    manager.poll()
    assert job.state == ("Stalled · retrying" if retry else "Paused")
    if retry:
        assert manager.retry_at == 10 and job.retries == 1
    manager.close()
