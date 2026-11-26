"""Inspect local inference files without contacting a model host."""
from dataclasses import dataclass
import json
from pathlib import Path

DOWNLOADING = set()


@dataclass(frozen=True)
class Ready:
    path: Path


@dataclass(frozen=True)
class Incomplete:
    have_bytes: int = 0
    total_bytes: int = 0


@dataclass(frozen=True)
class Missing:
    pass


@dataclass(frozen=True)
class Corrupt:
    reason: str = "The model file could not be read."


class ModelNotReady(RuntimeError):
    def __init__(self, spec, status):
        self.spec, self.status = spec, status
        super().__init__(model_hint(spec, status)[0])


def local_folder(repo, *, local_path=None, cache_roots=None):
    if local_path and Path(local_path).exists():
        path = Path(local_path)
        return path.parent if path.is_file() else path
    if cache_roots is None:
        from app_config import CONFIG_FILE
        registry = CONFIG_FILE.parent / "models" / "manifest.json"
        if registry.is_file():
            try:
                path = Path(json.loads(registry.read_text(encoding="utf-8"))[repo]["path"])
                if path.is_dir():
                    return path
            except (OSError, ValueError, KeyError):
                pass
        from huggingface_hub.constants import HF_HUB_CACHE
        cache_roots = [HF_HUB_CACHE]
    for root in cache_roots:
        base = Path(root) / ("models--" + repo.replace("/", "--"))
        ref = base / "refs" / "main"
        if ref.is_file():
            revision = ref.read_text().strip()
            folder = base / "snapshots" / revision
            if folder.is_dir():
                return folder
        snapshots = base / "snapshots"
        if snapshots.is_dir():
            folders = sorted((p for p in snapshots.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
            if folders:
                return folders[0]
        if base.is_dir():
            return base / "snapshots" / "main"
    return None


def inspect_model(spec, *, cache_roots=None):
    if spec.repo in DOWNLOADING:
        return Incomplete(0, spec.expected_size)
    folder = local_folder(spec.repo, local_path=spec.local_path, cache_roots=cache_roots)
    if folder is None:
        return Missing()
    try:
        manifest_path = folder / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("corrupt"):
                return Corrupt()
            files = manifest["files"]
            have = sum(min((folder / f["name"]).stat().st_size, f["size"]) for f in files if (folder / f["name"]).is_file())
            total = sum(f["size"] for f in files)
            for f in files:
                file = folder / f["name"]
                if not file.is_file() or file.stat().st_size < f["size"]:
                    return Incomplete(have, total)
                if file.stat().st_size != f["size"]:
                    return Corrupt()
            if not manifest.get("verified", True):
                return Incomplete(have, total)
        if spec.format == "ct2":
            required = [folder / "model.bin", folder / "config.json"]
            tokenizer = (folder / "tokenizer.json").is_file() or any(folder.glob("vocabulary.*"))
            complete = tokenizer and all(p.is_file() and p.stat().st_size for p in required)
        elif spec.format == "gguf":
            file = Path(spec.local_path)
            complete = file.is_file() and file.stat().st_size == spec.expected_size
        else:
            from engines.model_library import _complete
            complete = _complete(folder, spec.format)
        blobs = folder.parent.parent / "blobs" if folder.parent.name == "snapshots" else folder
        partials = list(blobs.rglob("*.incomplete")) if blobs.is_dir() else []
        if not complete or (not manifest_path.is_file() and partials):
            have = sum(p.stat().st_size for p in partials if p.is_file())
            if not have and folder.is_dir():
                have = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
            return Incomplete(have, spec.expected_size)
        return Ready(folder)
    except (OSError, ValueError, KeyError, TypeError):
        return Corrupt()


def whisper_spec(model):
    import os
    from app_config import CONFIG_FILE
    from model_loading import FAST_WHISPER_MODELS, fast_whisper_repo
    from engines.model_library import ModelSpec
    alias = FAST_WHISPER_MODELS.get(model, model)
    if model == "Seif-Eldeen-Sameh/whisper-medium-arabic-codeswitched-ct2":
        from engines.asr_codeswitch import codeswitch_directory
        path = codeswitch_directory()
    else:
        path = Path(os.environ["TRANSLITO_WHISPER_MODEL_DIR"]) if os.environ.get("TRANSLITO_WHISPER_MODEL_DIR") else CONFIG_FILE.parent / "models" / f"whisper-{alias}-ct2"
    title = {"large-v3-turbo": "Whisper Turbo", "small": "Whisper Small", "base": "Whisper Base"}.get(alias, f"Whisper {alias}")
    repo = fast_whisper_repo(alias) if model in FAST_WHISPER_MODELS else model
    return ModelSpec(model, title, "Speech", repo, "ct2", path,
                     expected_size={"large-v3-turbo": 1620000000, "small": 484000000, "base": 148000000}.get(alias, 0))


def ready_whisper(chosen, *, inspect=inspect_model):
    for model in dict.fromkeys([chosen, "openai/whisper-large-v3-turbo", "openai/whisper-small", "openai/whisper-base"]):
        if isinstance(inspect(whisper_spec(model)), Ready):
            return model
    return None


def mark_corrupt(folder):
    """Keep future preloads from trying a file the runtime rejected."""
    path = Path(folder) / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"files": []}
        manifest["corrupt"] = True
        path.write_text(json.dumps(manifest), encoding="utf-8")
    except (OSError, ValueError):
        pass


def missing_translations(source, target):
    from engines.mt_local import resolve_local_mt
    from engines.model_library import ModelSpec
    plan = resolve_local_mt(source, target, offline=True)
    specs = [ModelSpec(repo, f"Lite translation · {source} → {target}", "Translation", repo, "transformers") for repo in plan.repos]
    return [spec for spec in specs if not isinstance(inspect_model(spec), Ready)]


def model_hint(spec, status, fallback=None):
    if isinstance(status, Corrupt):
        return f"{spec.title} needs repair. Download it again to use it.", "Repair"
    if isinstance(status, Incomplete):
        total = status.total_bytes or spec.expected_size
        sizes = f" ({status.have_bytes / 1e9:.2f} of {total / 1e9:.2f} GB)" if total else ""
        suffix = f" Sessions use {fallback} until it finishes." if fallback else " Download it to start a session."
        return f"{spec.title} isn't fully downloaded{sizes}.{suffix}", "Resume download"
    return f"Download {spec.title} to start a session.", "Download"
