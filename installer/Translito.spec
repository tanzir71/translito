# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
from pathlib import Path
import sys

# Helpers run before Analysis applies pathex. build_windows.ps1 starts in
# installer/, so make the source package visible before collecting its assets.
repo_root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(repo_root))


hiddenimports = [
    "google.protobuf",
    "huggingface_hub",
    "keyboard",
    "sentencepiece",
    "soundcard",
    "sounddevice",
    "silero_vad",
    "faster_whisper",
    "ctranslate2",
]

# These packages load backends dynamically. Limit collection to the two
# model families Translito uses instead of bundling every Transformers model.
for package in (
    "pyttsx3",
    "transformers.models.marian",
    "transformers.models.whisper",
    "transformers.models.cohere_asr",
    "keyring.backends.Windows",
):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass


a = Analysis(
    [str(repo_root / "gui.py")],
    pathex=[str(repo_root)],
    binaries=collect_dynamic_libs("llama_cpp") + collect_dynamic_libs("engines"),
    datas=[("Translito.ico", "."), *collect_data_files("silero_vad"),
           (str(repo_root / "engines" / "data"), "engines/data")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cv2",
        "datasets",
        "flax",
        "jax",
        "keras",
        "matplotlib",
        "moviepy",
        "onnxruntime",
        "pandas",
        "sklearn",
        "tensorflow",
        "torchaudio",
        "torchvision",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Translito",
    icon="Translito.ico",
    version="version_info.txt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Translito",
)
