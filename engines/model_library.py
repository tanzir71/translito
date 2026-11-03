"""Offline model inventory and explicit, bounded model-cache operations."""
from dataclasses import dataclass
import gc
import json
import os
from pathlib import Path
import shutil
import stat


class ModelLibraryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    key: str
    title: str
    kind: str
    repo: str
    format: str
    local_path: Path | None = None
    setup: str = ""
    expected_size: int = 0


@dataclass(frozen=True)
class ModelEntry:
    spec: ModelSpec
    path: Path
    storage: str
    status: str
    size: int
    deletable: bool
    root: Path

    @property
    def key(self):
        return f"{self.spec.key}|{self.path}"


def format_size(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024


def _linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _safe_tree(path, root):
    """Validate absolute recursive targets, including Windows junction parents."""
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    if path == root or not path.is_relative_to(root) or not path.resolve().is_relative_to(root.resolve()):
        raise ModelLibraryError("The selected model is outside its cache folder.")
    current = path
    while current != root:
        if _linked(current):
            raise ModelLibraryError("Linked model folders cannot be deleted here.")
        current = current.parent
    if _linked(root):
        raise ModelLibraryError("Linked cache folders cannot be deleted here.")
    if path.is_dir():
        for base, dirs, _files in os.walk(path, followlinks=False):
            if any(_linked(Path(base) / name) for name in dirs):
                raise ModelLibraryError("Linked model folders cannot be deleted here.")
    return path


def _disk_size(path):
    if not path.exists() or _linked(path):
        return 0
    if path.is_file():
        return path.stat().st_size
    total, seen = 0, set()
    for base, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not _linked(Path(base) / name)]
        for name in files:
            item = Path(base) / name
            info = item.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            identity = (info.st_dev, info.st_ino)
            if identity not in seen:
                seen.add(identity)
                total += info.st_size
    return total


def _complete(folder, format):
    def present(name):
        p = folder / name
        return p.is_file() and p.stat().st_size > 0
    if format == "ct2":
        return all(present(name) for name in ("model.bin", "config.json", "tokenizer.json"))
    if not present("config.json"):
        return False
    if not any(present(name) for name in ("tokenizer.json", "source.spm", "vocab.json", "vocab.txt", "tokenizer.model", "spiece.model")):
        return False
    if present("model.safetensors") or present("pytorch_model.bin"):
        return True
    for name in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
        if present(name):
            try:
                weights = json.loads((folder / name).read_text(encoding="utf-8"))["weight_map"]
                return bool(weights) and all(Path(p).name == p and present(p) for p in weights.values())
            except (ValueError, KeyError, TypeError):
                return False
    return False


def default_catalog():
    from app_config import CONFIG_FILE
    from engines.asr_codeswitch import CODESWITCH_REPO, codeswitch_directory
    from engines.asr_cohere_local import MODEL_ID
    from engines.mt_local import KNOWN_PAIRS
    from engines.mt_translategemma import MANIFEST, configured_model_path
    from model_loading import fast_whisper_repo
    root = CONFIG_FILE.parent / "models"
    specs = [ModelSpec(f"whisper-{name}", f"Whisper {name}", "Speech", fast_whisper_repo(name), "ct2",
                       root / f"whisper-{name}-ct2")
             for name in ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")]
    override = os.environ.get("TRANSLITO_WHISPER_MODEL_DIR", "").strip()
    if override:
        specs.append(ModelSpec("custom-whisper", "Custom Whisper cache", "Speech", "", "ct2", Path(override).expanduser()))
    specs.extend((ModelSpec("codeswitch", "Arabic / English code-switch", "Speech", CODESWITCH_REPO,
                            "ct2", codeswitch_directory()),
                  ModelSpec("cohere", "Cohere Transcribe Arabic", "Speech", MODEL_ID, "transformers", setup="cohere"),
                  ModelSpec("gemma", "TranslateGemma 4B", "Translation", MANIFEST["repo"], "gguf",
                            configured_model_path(), "gemma", MANIFEST["bytes"])))
    specs.extend(ModelSpec(repo, f"Lite translation · {source} → {target}", "Translation", repo, "transformers")
                 for (source, target), repo in sorted(KNOWN_PAIRS.items()))
    return tuple(specs)


class ModelLibrary:
    def __init__(self, *, specs=None, models_root=None, hub_roots=None, protected_paths=None,
                 manager=None, session_active=None, offline=None):
        from app_config import CONFIG_FILE, load_cohere_cache_dir, load_transcript_folder
        from huggingface_hub.constants import HF_HUB_CACHE
        from model_loading import GLOBAL_MODEL_MANAGER
        self.specs = tuple(default_catalog() if specs is None else specs)
        self._default_specs = specs is None
        self._default_roots = hub_roots is None
        self.models_root = Path(models_root or CONFIG_FILE.parent / "models").absolute()
        roots = hub_roots if hub_roots is not None else [HF_HUB_CACHE, load_cohere_cache_dir()]
        self.hub_roots = tuple(dict.fromkeys(Path(p).expanduser().absolute() for p in roots if p))
        if not self.hub_roots:
            raise ValueError("At least one Hugging Face cache folder is required.")
        self.protected = tuple(Path(p).absolute() for p in (protected_paths if protected_paths is not None else
                               (CONFIG_FILE, load_transcript_folder(), CONFIG_FILE.parent / "usage.json")))
        self.manager = manager or GLOBAL_MODEL_MANAGER
        self.session_active = session_active or (lambda: False)
        self.offline = offline or (lambda: False)

    def inventory(self):
        from huggingface_hub import scan_cache_dir
        if self._default_specs:
            self.specs = default_catalog()
        if self._default_roots:
            from app_config import load_cohere_cache_dir
            from huggingface_hub.constants import HF_HUB_CACHE
            self.hub_roots = tuple(dict.fromkeys(Path(p).expanduser().absolute() for p in
                                                (HF_HUB_CACHE, load_cohere_cache_dir()) if p))
        cached = {}
        for root in self.hub_roots:
            if root.is_dir() and not _linked(root):
                for repo in scan_cache_dir(root).repos:
                    if repo.repo_type == "model":
                        cached[repo.repo_path.absolute()] = repo
        specs = list(self.specs)
        known = {s.repo for s in specs}
        for repo in cached.values():
            if repo.repo_id not in known and repo.repo_id.startswith(("openai/whisper-", "Helsinki-NLP/opus-mt-")):
                specs.append(ModelSpec(repo.repo_id, repo.repo_id, "Speech" if repo.repo_id.startswith("openai/") else "Translation",
                                       repo.repo_id, "transformers"))
                known.add(repo.repo_id)
        entries = []
        for spec in specs:
            copies = []
            if spec.local_path is not None:
                path = spec.local_path.expanduser().absolute()
                if path.exists():
                    complete = (path.is_file() and path.stat().st_size > 0 and
                                (not spec.expected_size or path.stat().st_size == spec.expected_size)) if spec.format == "gguf" else _complete(path, spec.format)
                    managed = path.resolve().is_relative_to(self.models_root.resolve())
                    codeswitch = spec.key == "codeswitch" and path.name == "whisper-arabic-codeswitch-ct2" and not os.environ.get("TRANSLITO_CODESWITCH_MODEL_DIR")
                    managed = managed or codeswitch
                    allowed = path.is_file() and path.suffix.lower() == ".gguf" if spec.format == "gguf" else managed
                    copies.append(ModelEntry(spec, path, "Model file" if spec.format == "gguf" else "App cache" if managed else "External folder",
                                              "Downloaded" if complete else "Partial", _disk_size(path), allowed and not _linked(path),
                                              path.parent if spec.format == "gguf" or codeswitch else self.models_root))
                if spec.format == "gguf":
                    partial_root = path.parent / ".cache" / "huggingface" / "download"
                    if partial_root.is_dir() and not _linked(partial_root):
                        for partial in partial_root.glob(path.name + ".*.incomplete"):
                            if partial.is_file() and not _linked(partial):
                                copies.append(ModelEntry(spec, partial, "Partial download", "Partial", partial.stat().st_size,
                                                          True, path.parent))
            if spec.repo and spec.format != "gguf":
                for root in self.hub_roots:
                    path = root / ("models--" + spec.repo.replace("/", "--"))
                    if path.is_dir():
                        snapshots = path / "snapshots"
                        complete = snapshots.is_dir() and not _linked(snapshots) and any(
                            _complete(p, spec.format) for p in snapshots.iterdir() if p.is_dir() and not _linked(p))
                        size = cached[path].size_on_disk if path in cached else _disk_size(path)
                        copies.append(ModelEntry(spec, path, "Shared Hugging Face cache", "Downloaded" if complete else "Partial",
                                                  size, not _linked(path), root))
            if not copies:
                path = spec.local_path if spec.local_path else self.hub_roots[0] / ("models--" + spec.repo.replace("/", "--"))
                copies.append(ModelEntry(spec, Path(path).absolute(), "Model file" if spec.format == "gguf" else "Available",
                                          "Available", 0, False, self.models_root))
            entries.extend(copies)
        return entries

    def _guard(self):
        if self.session_active():
            raise ModelLibraryError("Stop the current session before managing model files.")

    def _fresh(self, entry):
        found = next((row for row in self.inventory() if row.key == entry.key), None)
        if found is None:
            raise ModelLibraryError("The model cache changed. Refresh the list and try again.")
        return found

    def _release(self):
        from engines.asr_local import _lid_model, _cohere_model
        from engines.mt_translategemma import cached_translator
        _lid_model.cache_clear()
        _cohere_model.cache_clear()
        cached_translator.cache_clear()
        gc.collect()

    def delete(self, entry, *, confirmed=False):
        if confirmed is not True:
            raise ModelLibraryError("Confirm the selected model deletion first.")
        self._guard()
        with self.manager.maintenance():
            self._guard()
            row = self._fresh(entry)
            if not row.deletable or not row.path.exists():
                raise ModelLibraryError("This model is external, linked, or already removed. Refresh the list.")
            path = _safe_tree(row.path, row.root)
            if row.spec.format == "gguf" and not path.is_file():
                raise ModelLibraryError("Only the selected model file can be removed; its folder was preserved.")
            if any(p.resolve() == path.resolve() or p.resolve().is_relative_to(path.resolve()) or
                   (p.is_dir() and path.resolve().is_relative_to(p.resolve())) for p in self.protected):
                raise ModelLibraryError("This folder contains settings or transcripts; its files were preserved.")
            self._release()
            if row.storage == "Shared Hugging Face cache":
                self._delete_hub(row)
            elif path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
            if path.exists():
                raise ModelLibraryError("Some model files are still in use. Close other apps using this model and retry.")
            return row.size

    def _delete_hub(self, row):
        from huggingface_hub import scan_cache_dir
        cache = scan_cache_dir(row.root)
        repo = next((r for r in cache.repos if r.repo_path.absolute() == row.path), None)
        if repo is None:  # Interrupted downloads with no complete revision.
            shutil.rmtree(row.path)
            return
        plan = cache.delete_revisions(*(r.commit_hash for r in repo.revisions))
        for field in ("repos", "snapshots", "refs", "files", "blobs"):
            for candidate in getattr(plan, field, ()):
                candidate = Path(candidate).absolute()
                # The SDK handles reference-counted shared blobs. Other model
                # directories must never be part of this model's delete plan.
                if not (candidate.is_relative_to(row.path) or
                        (field == "blobs" and candidate.is_relative_to(row.root / "blobs"))):
                    raise ModelLibraryError("The cache plan includes another model; no files were deleted.")
                _safe_tree(candidate, row.root)
        plan.execute()

    def download(self, entry, *, on_event=None):
        self._guard()
        if self.offline():
            raise ModelLibraryError("Offline mode is on. Turn it off before downloading models.")
        entry = self._fresh(entry)
        if entry.spec.setup:
            raise ModelLibraryError("Open model setup to review the terms before downloading this model.")
        if not entry.spec.repo:
            raise ModelLibraryError("This is an externally configured model folder.")
        with self.manager.maintenance():
            self._guard()
            self._release()
            try:
                if entry.spec.key == "codeswitch":
                    from engines.asr_codeswitch import prepare_codeswitch_model
                    return prepare_codeswitch_model(on_event=on_event)
                from model_loading import _download_repo_with_progress
                from huggingface_hub import HfApi
                names = [file.rfilename for file in HfApi(token=False).model_info(entry.spec.repo).siblings]
                weights = ["*.safetensors"] if any(name.endswith(".safetensors") for name in names) else ["pytorch_model*.bin"]
                patterns = (["*.json", "*.txt", "model.bin", "vocabulary.*"] if entry.spec.format == "ct2" else
                            ["*.json", "*.spm", "*.txt", *weights])
                _download_repo_with_progress(entry.spec.repo, entry.spec.title, 0, 1, on_event,
                                             cache_dir=self.hub_roots[0], token=False, allow_patterns=patterns)
            except Exception:
                raise ModelLibraryError("Download failed. Check your connection and free disk space; partial files are kept for retry.") from None
