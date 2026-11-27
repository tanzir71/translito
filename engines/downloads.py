"""Persistent, serial download queue. Only the child imports download SDKs."""
from dataclasses import dataclass, asdict, field
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

from engines.model_files import DOWNLOADING as _locks


def model_locked(repo):
    return repo in _locks


def job_for_repo(jobs, repo):
    matching = [job for job in jobs if job.repo == repo]
    return (next((job for job in matching if job.state in {"Downloading", "Verifying", "Stalled · retrying", "Queued"}), None)
            or next((job for job in reversed(matching) if job.state != "Ready"), None)
            or next(iter(reversed(matching)), None))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


@dataclass
class DownloadJob:
    id: str
    repo: str
    title: str
    folder: str
    format: str = "ct2"
    revision: str = "main"
    files: list = field(default_factory=list)
    total: int = 0
    bytes: int = 0
    bytes_per_s: float = 0
    state: str = "Queued"
    retries: int = 0
    error: str = ""
    fetcher: str = ""
    gemma: bool = False
    credential: str = ""
    registry_path: str = ""
    ready_path: str = ""
    cache_dir: str = ""
    origin: str = "manual"
    pause_reason: str = ""
    priority: int = 50
    context: str = ""
    error_code: str = ""

    @property
    def fraction(self):
        return 1 if self.state == "Ready" else min(1, self.bytes / self.total) if self.total else 0

    @property
    def progress_text(self):
        from engines.model_library import format_size
        remaining = max(0, self.total - self.bytes)
        eta = f" · about {max(1, round(remaining/self.bytes_per_s/60))} min left" if self.bytes_per_s else ""
        return f"{self.state} · {format_size(self.bytes)} of {format_size(self.total)} · {format_size(self.bytes_per_s)}/s{eta}"


class DownloadManager:
    def __init__(self, root=None, *, directory=None, on_change=lambda job: None,
                 blocked=lambda: False, clock=time.monotonic, spawn=subprocess.Popen,
                 disk_usage=shutil.disk_usage):
        if directory is None:
            from app_config import CONFIG_FILE
            directory = CONFIG_FILE.parent / "downloads"
        self.directory = Path(directory)
        self.root, self.on_change, self.blocked = root, on_change, blocked
        self.clock, self.spawn, self.disk_usage = clock, spawn, disk_usage
        self.jobs, self.events = [], queue.Queue()
        self.process, self.active, self.last_progress = None, None, 0
        self.last_child_bytes = 0
        self.retry_at, self.closed, self.timer = 0, False, None
        self.generation = ""
        self._process_lock = threading.RLock()
        for path in sorted(self.directory.glob("*.json")):
            try:
                job = DownloadJob(**json.loads(path.read_text(encoding="utf-8")))
                if job.state not in {"Ready", "Cancelled", "Paused"}:
                    job.state = "Queued"
                self.jobs.append(job)
                self.adopt_cached(job)
            except (OSError, ValueError, TypeError):
                continue
        if root is not None:
            self.timer = root.after(250, self.poll)

    def save(self, job):
        _write(self.directory / f"{job.id}.json", asdict(job))

    def adopt_cached(self, job):
        """A saved queue failure cannot override an already available model."""
        if job is self.active or job.state in {"Ready", "Cancelled"} or job.format not in {"ct2", "transformers"} or job.gemma:
            return False
        from engines.model_files import Ready, inspect_model
        from engines.model_library import ModelSpec
        spec = ModelSpec(job.repo, job.title, "Cached model", job.repo, job.format,
                         Path(job.ready_path or job.folder), expected_size=job.total)
        status = inspect_model(spec)
        if not isinstance(status, Ready):
            return False
        job.ready_path, job.state = str(status.path), "Ready"
        job.error = job.error_code = job.pause_reason = ""
        job.bytes_per_s = 0
        manifest = status.path / "manifest.json"
        if manifest.is_file():
            try:
                job.total = sum(file["size"] for file in json.loads(manifest.read_text(encoding="utf-8"))["files"])
            except (OSError, ValueError, KeyError, TypeError):
                pass
        job.bytes = job.total
        self.save(job)
        return True

    def enqueue_model(self, spec, *, folder=None, **options):
        if self.blocked():
            raise ValueError("Internet is blocked. Allow internet access before downloading models.")
        existing = next((j for j in self.jobs if j.repo == spec.repo and j.state not in {"Ready", "Cancelled"}), None)
        if existing:
            if options.get("origin", "manual") == "manual":
                self.resume(existing)
            return existing
        from app_config import CONFIG_FILE
        from engines.model_files import local_folder, inspect_model, Incomplete
        cached = local_folder(spec.repo, local_path=spec.local_path)
        options = dict(options)
        if (folder is None and cached is not None and cached.parent.name == "snapshots" and spec.format != "gguf"
                and (spec.local_path is None or spec.key.startswith(("whisper-", "openai/whisper-")))):
            folder = cached
            options.setdefault("cache_dir", str(cached.parent.parent.parent))
            options.setdefault("revision", cached.name)
        folder = Path(folder or spec.local_path or CONFIG_FILE.parent / "models" / spec.repo.replace("/", "--"))
        if spec.format == "gguf" and folder.suffix == ".gguf":
            folder = folder.parent
        registry = CONFIG_FILE.parent / "models" / "manifest.json"
        status = inspect_model(spec)
        job = DownloadJob(uuid4().hex, spec.repo, spec.title, str(folder), spec.format,
                          total=spec.expected_size, registry_path=str(registry), **options)
        if isinstance(status, Incomplete):
            job.bytes = status.have_bytes
            job.total = status.total_bytes or job.total
        self.enqueue(job)
        return job

    def enqueue(self, job):
        if self.blocked():
            raise ValueError("Internet is blocked.")
        existing = Path(job.folder)
        while not existing.exists():
            existing = existing.parent
        if self.disk_usage(existing).free < max(0, job.total - job.bytes) + 500000000:
            raise ValueError(f"Free at least {(max(0, job.total-job.bytes)+500000000)/1e9:.2f} GB in the selected folder.")
        self.jobs.append(job)
        self.save(job)
        self.on_change(job)

    def _start(self, job):
        if self.blocked():
            job.state, job.error, job.pause_reason = "Paused", "Internet is blocked.", "blocked"
            self.save(job)
            self.on_change(job)
            return
        job.state, job.error, job.error_code = "Downloading", "", ""
        self.save(job)
        command = ([sys.executable] if getattr(sys, "frozen", False) else
                   [sys.executable, str(Path(__file__).resolve().parents[1] / "gui.py")])
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0
        with self._process_lock:
            self.active, self.last_progress = job, self.clock()
            self.generation = generation = uuid4().hex
        self.last_child_bytes = 0
        _locks.add(job.repo)
        def launch():
            try:
                process = self.spawn(command + ["--download-job", str(self.directory / f"{job.id}.json")],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=flags)
            except OSError:
                self.events.put((generation, {"startup_error": True}))
                return
            with self._process_lock:
                accepted = not self.closed and self.active is job and self.generation == generation
                if accepted:
                    self.process = process
            if not accepted:
                process.terminate()
                process.wait()
                return
            threading.Thread(target=read, args=(process,), daemon=True, name="Model download progress").start()
        def read(process):
            for line in process.stdout:
                try:
                    self.events.put((generation, json.loads(line)))
                except (ValueError, TypeError):
                    continue
            self.events.put((generation, {"exit": process.wait()}))
        if self.root is None:
            launch()
        else:
            threading.Thread(target=launch, daemon=True, name="Start model download").start()
        self.on_change(job)

    def _stop(self):
        with self._process_lock:
            process, active = self.process, self.active
            self.active, self.process, self.generation = None, None, ""
        if process is not None and process.poll() is None:
            process.terminate()
            # Reap off the Tk thread; terminate keeps all SDK partial files.
            threading.Thread(target=process.wait, daemon=True).start()
        if active:
            _locks.discard(active.repo)

    def pause(self, job, *, state="Paused", reason="user"):
        if self.active is job:
            self._stop()
        job.state, job.pause_reason = state, reason
        job.bytes_per_s = 0
        self.save(job)
        self.on_change(job)

    def cancel(self, job):
        # Cancel the logical model request, including duplicate stale attempts.
        affected = [j for j in self.jobs if j.repo == job.repo and j.state != "Ready"]
        if not affected:
            return
        if self.active in affected:
            self._stop()
        for current in affected:
            current.state, current.pause_reason = "Cancelled", "user"
            current.error = current.error_code = ""
            current.bytes_per_s = 0
            self.save(current)
        for current in affected:
            self.on_change(current)

    def resume(self, job, *, automatic=False):
        if self.blocked():
            raise ValueError("Internet is blocked. Allow internet access before resuming downloads.")
        # An explicit Resume takes ownership from automatic pair preparation.
        # Otherwise the next readiness refresh can supersede or preempt it again.
        if not automatic and job.origin != "manual":
            job.origin = "manual"
            self.save(job)
        if job.state in {"Downloading", "Queued", "Stalled · retrying"}:
            return
        job.state, job.retries, job.error, job.error_code, job.pause_reason = "Queued", 0, "", "", ""
        self.save(job)
        self.on_change(job)

    def _retry(self, job, *, notify=True):
        self._stop()
        job.bytes_per_s = 0
        if job.retries >= 3:
            job.state, job.error, job.pause_reason = "Paused", job.error or "Paused · check your connection", "failure"
        else:
            self.retry_at = self.clock() + (10, 30, 60)[job.retries]
            job.retries += 1
            job.state = "Stalled · retrying"
        if notify:
            self.save(job)
            self.on_change(job)

    def poll(self):
        if self.closed:
            return
        changed = {}
        while True:
            try:
                identity, data = self.events.get_nowait()
            except queue.Empty:
                break
            job = self.active
            if job is None or self.generation != identity:
                continue
            if data.get("startup_error"):
                job.state, job.error, job.pause_reason = "Paused", "Couldn't start the download. Try again.", "failure"
                self._stop()
            if "bytes" in data:
                if "file" in data:
                    job.state = "Downloading"
                # Byte growth, not repeated heartbeat lines, resets a stall.
                if data["bytes"] > self.last_child_bytes:
                    self.last_progress = self.clock()
                    self.last_child_bytes = data["bytes"]
                job.total = data["total"]
                job.bytes = min(job.total, max(job.bytes, data["bytes"]))
                job.bytes_per_s = data.get("bytes_per_s", 0)
            if data.get("stage") == "Verifying":
                self.last_progress = self.clock()
                job.state = "Verifying"
            elif data.get("stage") == "Checking cache":
                self.last_progress = self.clock()
            if "ready" in data:
                job.ready_path, job.state = data["ready"], "Ready"
                job.bytes = job.total
                self._stop()
            elif "error" in data:
                job.error = data["error"]
                job.error_code = data.get("error_code", "")
                if data.get("retryable"):
                    self._retry(job, notify=False)
                else:
                    job.state, job.pause_reason = "Paused", "failure"
                    self._stop()
            elif "exit" in data:
                self._retry(job, notify=False)
            changed[job.id] = job
        # Hash verification can emit dozens of messages in one UI frame.
        # Persist and render the latest state once, rather than blocking Tk
        # on a separate atomic disk write for every queued heartbeat.
        for job in changed.values():
            self.save(job)
            self.on_change(job)
        if self.active and self.clock() - self.last_progress >= 60:
            self._retry(self.active)
        if self.active is None:
            next_job = next(iter(sorted((j for j in self.jobs if j.state == "Queued" or
                (j.state == "Stalled · retrying" and self.clock() >= self.retry_at)), key=lambda j: j.priority)), None)
            if next_job:
                self._start(next_job)
        if self.root is not None:
            self.timer = self.root.after(250, self.poll)

    def reconcile_setup(self, required, backup=(), *, context="", enabled=True):
        """Prioritize the current pair without undoing a user's Pause/Cancel."""
        from engines.model_files import Ready, inspect_model
        desired = {spec.repo: (spec, priority) for priority, specs in ((20, backup), (0, required)) for spec in specs}
        for job in tuple(self.jobs):
            if self.adopt_cached(job):
                self.on_change(job)
            if job.state == "Ready":
                continue
            if job.origin != "auto_setup":
                priority = desired[job.repo][1] if job.repo in desired else 50
                if job.priority != priority:
                    job.priority = priority
                    self.save(job)
                    self.on_change(job)
                continue
            if not enabled or job.repo not in desired:
                if job.state in {"Queued", "Downloading", "Verifying", "Stalled · retrying"}:
                    self.pause(job, reason="superseded" if enabled else "policy")
            else:
                spec, priority = desired[job.repo]
                changed = (job.priority, job.context, job.title) != (priority, context, spec.title)
                job.priority, job.context, job.title = priority, context, spec.title
                if job.state == "Paused" and job.pause_reason in {"superseded", "policy", "blocked"} and not self.blocked():
                    self.resume(job, automatic=True)
                if changed:
                    self.save(job)
                    self.on_change(job)
        if enabled and not self.blocked():
            for spec, priority in sorted(desired.values(), key=lambda item: item[1]):
                if isinstance(inspect_model(spec), Ready):
                    continue
                current = job_for_repo(self.jobs, spec.repo)
                if current is None or current.state == "Ready":
                    self.enqueue_model(spec, origin="auto_setup", priority=priority, context=context)
        active = self.active
        urgent = next((j for j in sorted(self.jobs, key=lambda j: j.priority) if j.state == "Queued"), None)
        if active and active.origin == "auto_setup" and urgent and urgent.priority < active.priority and active.state != "Verifying":
            self.pause(active, reason="preempted")
        # A preempted job remains queued behind the new mandatory resource.
        for job in self.jobs:
            if job.state == "Paused" and job.pause_reason == "preempted" and job.repo in desired and enabled and not self.blocked():
                self.resume(job, automatic=True)

    def block_network(self):
        for job in tuple(self.jobs):
            if job.state in {"Queued", "Downloading", "Verifying", "Stalled · retrying"}:
                self.pause(job, reason="blocked")

    def close(self):
        self.closed = True
        if self.root is not None and self.timer:
            self.root.after_cancel(self.timer)
        if self.active:
            job = self.active
            self._stop()
            job.state = "Queued"
            self.save(job)


def _plan(job, token):
    from huggingface_hub import HfApi
    import fnmatch
    info = HfApi(token=token).model_info(job.repo, revision=job.revision, files_metadata=True, timeout=20)
    patterns = (["*.gguf"] if job.format == "gguf" else
                ["*.json", "model.bin", "vocabulary.*", "*.txt"] if job.format == "ct2" else
                ["*.json", "*.safetensors", "*.spm", "*.model", "*.txt", "*.bin"])
    result = []
    for item in info.siblings:
        name = item.rfilename
        if not any(fnmatch.fnmatch(name, p) for p in patterns) or "/" in name:
            continue
        if job.files and name not in {f["name"] for f in job.files}:
            continue
        lfs = item.lfs
        result.append({"name": name, "size": item.size or 0, "sha256": getattr(lfs, "sha256", None)})
    if job.format == "transformers" and any(f["name"].endswith(".safetensors") for f in result):
        result = [f for f in result if not (f["name"].startswith("pytorch_model") and f["name"].endswith(".bin"))]
    if job.gemma:
        from engines.mt_translategemma import MANIFEST
        result = [{"name": MANIFEST["filename"], "size": MANIFEST["bytes"], "sha256": MANIFEST["sha256"]}]
    return info.sha, result


def write_json_line(value, *, stream=None, kernel32=None):
    """Windowed PyInstaller children can have sys.stdout=None with a valid pipe."""
    line = json.dumps(value) + "\n"
    stream = sys.stdout if stream is None else stream
    if stream is not None:
        stream.write(line)
        stream.flush()
        return
    import ctypes
    api = kernel32 or ctypes.windll.kernel32
    if isinstance(api, ctypes.CDLL):
        api.GetStdHandle.restype = ctypes.c_void_p
        api.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    payload = line.encode("utf-8")
    buffer = ctypes.create_string_buffer(payload)
    written = ctypes.c_uint32()
    if not api.WriteFile(api.GetStdHandle(-11), buffer, len(payload), ctypes.byref(written), None):
        raise BrokenPipeError("The download progress pipe is closed")


def _progress_class(report):
    """Read HTTP/Xet transfer progress even before buffered bytes reach disk."""
    from tqdm import tqdm

    class DownloadProgress(tqdm):
        def __init__(self, *args, **kwargs):
            kwargs["disable"] = True  # A windowed child has no terminal stream.
            super().__init__(*args, **kwargs)
            self.transferred = 0
            report(self.n)

        def update(self, n=1):
            self.n += n
            report(max(self.n, self.transferred))

        def update_transfer(self, n):
            self.transferred += n
            report(max(self.n, self.transferred))

        def set_transfer_postfix_str(self, *args, **kwargs):
            pass

    return DownloadProgress


def _materialize_cache_link(path):
    from engines.model_files import materialize_cache_link
    materialize_cache_link(path, allow_copy=True)


def _file_size(path):
    # The SDK renames temporary files atomically while progress is sampled.
    try:
        _materialize_cache_link(path)
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _remote_failure(error):
    """SDK messages can contain credentials or signed URLs; emit safe reasons."""
    import httpx
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429 or isinstance(status, int) and status >= 500:
        return {"error": "The model server is busy. Retrying; partial files are kept.", "retryable": True}
    if isinstance(error, (httpx.RequestError, TimeoutError, ConnectionError)):
        return {"error": "The model server connection was interrupted. Retrying; partial files are kept.", "retryable": True}
    if status in {401, 403}:
        return {"error": "Model access was denied. Check the model's access requirements in Models."}
    if status == 404:
        return {"error": "The selected model revision is unavailable. Choose the model again in Models."}
    return {"error": "Download failed. Check your connection or model access. Partial files are kept for Resume."}


def _retryable_cache_error(error):
    if getattr(error, "winerror", None) == 448:
        return False
    if getattr(error, "winerror", None) in {32, 33, 121, 995, 1460}:
        return True
    return (isinstance(error, OSError) and not isinstance(error, (PermissionError, FileNotFoundError))
            and error.errno != 28 and getattr(error, "winerror", None) != 112)


def _setup_failure(error, phase):
    """Keep useful failure diagnostics without SDK URLs, tokens or raw paths."""
    if getattr(error, "winerror", None) == 448:
        message = "Windows blocked a link in the model cache. Choose another model folder in Models."
    elif isinstance(error, PermissionError):
        message = ("Windows blocked saving model setup. Check access to Translito's app data folder."
                   if phase == "register_model" else
                   "Windows blocked access to the model folder. Choose another folder in Models.")
    elif isinstance(error, OSError) and (error.errno == 28 or getattr(error, "winerror", None) == 112):
        message = "The disk is full. Free space, then Resume model setup."
    elif isinstance(error, ImportError):
        message = "A model setup component is missing. Reinstall the latest Translito installer."
    elif isinstance(error, FileNotFoundError):
        message = "The saved model folder or setup request is unavailable. Choose the model again in Models."
    elif type(error) is ValueError:
        message = str(error)
    else:
        stage = {"read_request": "reading its saved request", "secure_connection": "preparing the secure connection",
                 "check_cache": "checking cached files", "write_manifest": "saving model metadata",
                 "verify_files": "verifying model files", "register_model": "saving model setup"}.get(phase, "preparing model files")
        message = f"Model setup could not finish while {stage}. Retry in Models."
    operation = getattr(error, "cache_operation", "")
    code = f"{phase}:{type(error).__name__}" + (f":{operation}" if operation else "")
    for name in ("errno", "winerror"):
        value = getattr(error, name, None)
        if isinstance(value, int):
            code += f":{name}={value}"
    result = {"error": message, "error_code": code}
    if phase == "check_cache" and _retryable_cache_error(error):
        result["retryable"] = True
    return result


def _check_cached_files(folder, files, cache_dir):
    operation = "file_sizes"
    try:
        total = sum(file["size"] for file in files)
        have = sum(min(_file_size(folder / file["name"]), file["size"]) for file in files)
        if have < total:
            operation = "partial_files"
            partial_root = folder.parent.parent / "blobs" if cache_dir else folder
            partial = sum(_file_size(path) for path in partial_root.rglob("*.incomplete"))
            operation = "free_space"
            required = max(0, total - have - partial) + 500000000
            if shutil.disk_usage(folder).free < required:
                raise ValueError(f"Not enough disk space. Free at least {required / 1e9:.2f} GB in the selected folder.")
        operation = "manifest"
        repair = False
        if (folder / "manifest.json").is_file():
            try:
                repair = json.loads((folder / "manifest.json").read_text(encoding="utf-8")).get("corrupt", False)
            except ValueError:
                repair = True
        return total, repair
    except OSError as error:
        error.cache_operation = operation
        raise


def download_child(path):
    """Early GUI dispatch target; never imports Tk, tray, hotkeys or audio."""
    def emit(value):
        write_json_line(value)
    phase = "read_request"
    try:
        job = DownloadJob(**json.loads(Path(path).read_text(encoding="utf-8")))
        phase = "prepare_folder"
        folder = Path(job.folder).resolve()
        if not job.cache_dir:
            folder.mkdir(parents=True, exist_ok=True)
        phase = "secure_connection"
        from native_tls import configure_native_tls
        configure_native_tls()
        token = False
        if job.credential:
            from engines.secrets import CredentialStore
            token = CredentialStore().get(job.credential)
        if job.fetcher:
            import importlib.util
            module = importlib.util.spec_from_file_location("download_fetcher", job.fetcher)
            fetcher = importlib.util.module_from_spec(module)
            module.loader.exec_module(fetcher)
            revision, files = job.revision, job.files
        else:
            try:
                revision, files = _plan(job, token)
            except Exception as error:
                emit(_remote_failure(error))
                return 1
            fetcher = None
        phase = "prepare_folder"
        if job.cache_dir:
            folder = Path(job.cache_dir) / ("models--" + job.repo.replace("/", "--")) / "snapshots" / revision
            folder.mkdir(parents=True, exist_ok=True)
        if not files:
            raise ValueError("No inference files were found for this model.")
        phase = "check_cache"
        for attempt in range(4):
            try:
                total, repair = _check_cached_files(folder, files, job.cache_dir)
                break
            except OSError as error:
                if attempt == 3 or not _retryable_cache_error(error):
                    raise
                emit({"stage": "Checking cache"})
                time.sleep((.25, .75, 1.5)[attempt])
        partial_root = folder.parent.parent / "blobs" if job.cache_dir else folder
        manifest = {"repo": job.repo, "revision": revision, "files": files, "verified": False}
        phase = "write_manifest"
        _write(folder / "manifest.json", manifest)
        completed = 0
        for file in files:
            phase = "download_file"
            name = file["name"]
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError("The model contains an unsafe file name.")
            errors, done = [], threading.Event()
            result = []
            transferred = [0]
            def report(count):
                transferred[0] = max(transferred[0], count)
            progress = _progress_class(report)
            def fetch():
                try:
                    if fetcher:
                        result.append(fetcher.fetch(job, file, folder))
                    else:
                        from huggingface_hub import hf_hub_download
                        result.append(hf_hub_download(job.repo, name, revision=revision,
                            **({"cache_dir": job.cache_dir} if job.cache_dir else {"local_dir": folder}),
                            token=token, force_download=repair, tqdm_class=progress))
                    _materialize_cache_link(Path(result[-1]))
                except Exception as error:
                    errors.append(error)
                finally:
                    done.set()
            threading.Thread(target=fetch, daemon=True).start()
            previous, at = 0, time.monotonic()
            while True:
                finished = done.wait(.25)
                final = folder / name
                size = max(_file_size(final), transferred[0])
                partials = ([partial_root / (file["sha256"] + ".incomplete")] if job.cache_dir and file.get("sha256")
                            else list(partial_root.rglob("*.incomplete")))
                size = max(size, max((_file_size(p) for p in partials), default=0))
                # A fetcher can atomically rename .incomplete between the two
                # probes above. That is completion, not lost download progress.
                size = max(previous, size)
                now = time.monotonic()
                emit({"file": name, "bytes": completed + min(size, file["size"]), "total": total,
                      "bytes_per_s": max(0, size-previous)/max(.001, now-at)})
                previous, at = size, now
                if finished:
                    break
            if errors:
                emit(_remote_failure(errors[0]))
                return 1
            phase = "verify_files"
            final = Path(result[0])
            if final.stat().st_size != file["size"]:
                raise ValueError("The downloaded file has the wrong size. Use Repair to download it again.")
            digest = hashlib.sha256()
            with final.open("rb") as handle:
                for chunk in iter(lambda: handle.read(4*1024*1024), b""):
                    digest.update(chunk)
                    emit({"stage": "Verifying"})
            if file.get("sha256") and digest.hexdigest() != file["sha256"]:
                manifest["corrupt"] = True
                _write(folder / "manifest.json", manifest)
                raise ValueError("Checksum mismatch. Use Repair to download this file again.")
            completed += file["size"]
        if job.gemma:
            phase = "verify_model"
            from engines.mt_translategemma import TranslateGemma, MANIFEST
            from llama_cpp import Llama
            # The bytes above have passed SHA-256. The manifest stays unavailable
            # to sessions until this first load also verifies the chat template.
            model = TranslateGemma(folder / MANIFEST["filename"], loader=Llama)
            model.load()
            model.model.close()
        if job.repo == "Seif-Eldeen-Sameh/whisper-medium-arabic-codeswitched-ct2":
            from huggingface_hub import hf_hub_download
            from engines.asr_codeswitch import TOKENIZER_REPO, validate_tokenizer
            hf_hub_download(TOKENIZER_REPO, "tokenizer.json", local_dir=folder, token=False)
            validate_tokenizer(folder)
        if job.registry_path:
            phase = "register_model"
            registry_path = Path(job.registry_path)
            registry = json.loads(registry_path.read_text()) if registry_path.is_file() else {}
            registry[job.repo] = {"path": str(folder), **manifest}
            registry[job.repo]["verified"] = True
            _write(registry_path, registry)
        phase = "write_manifest"
        manifest["verified"] = True
        _write(folder / "manifest.json", manifest)
        emit({"ready": str(folder), "bytes": total, "total": total})
        return 0
    except Exception as error:
        emit(_setup_failure(error, phase))
        return 1
