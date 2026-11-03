"""Offline dependency probe used to verify the actual frozen Windows runtime."""

import importlib
import json
from pathlib import Path
import sys


def check_runtime():
    results = {}
    for name in ("numpy", "torch", "transformers", "faster_whisper",
                 "sentencepiece", "google.protobuf", "soundcard", "sounddevice"):
        try:
            module = importlib.import_module(name)
            if name == "torch":
                # Import alone does not prove the native CPU backend can run.
                if module.tensor([1.0, 2.0]).sum().item() != 3.0:
                    raise RuntimeError("CPU tensor calculation failed")
            elif name == "transformers":
                # Resolve the lazy pipeline import checked at GUI startup.
                getattr(module, "pipeline")
            results[name] = {"ok": True, "version": getattr(module, "__version__", None)}
        except Exception as exc:
            results[name] = {"ok": False, "error": str(exc)}
    return {"ok": all(result["ok"] for result in results.values()),
            "frozen": bool(getattr(sys, "frozen", False)), "dependencies": results}


def check_main(arguments):
    if len(arguments) != 1 or not Path(arguments[0]).is_absolute():
        return 2
    try:
        # Never overwrite an existing report or create arbitrary parent folders.
        with Path(arguments[0]).open("x", encoding="utf-8") as report_file:
            report = check_runtime()
            json.dump(report, report_file, indent=2)
        return 0 if report["ok"] else 1
    except OSError:
        return 2
