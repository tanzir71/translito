import json
from types import SimpleNamespace

import pytest

import runtime_check


_real_import = runtime_check.importlib.import_module


def fake_import(name):
    if name.startswith("tzdata.zoneinfo"):
        return _real_import(name)
    if name == "torch":
        return SimpleNamespace(tensor=lambda data: SimpleNamespace(
            sum=lambda: SimpleNamespace(item=lambda: sum(data))))
    if name == "native_tls":
        return SimpleNamespace(configure_native_tls=lambda: None)
    return SimpleNamespace(pipeline=object())


def test_probe_exercises_native_tensor_and_lazy_pipeline(monkeypatch):
    monkeypatch.setattr(runtime_check.importlib, "import_module", fake_import)
    assert runtime_check.check_runtime()["ok"]


@pytest.mark.parametrize("failed", ["torch", "transformers"])
def test_probe_records_failure_and_checks_remaining_dependencies(monkeypatch, failed):
    def importer(name):
        if name == failed:
            raise OSError("[WinError 126] missing native dependency")
        return fake_import(name)
    monkeypatch.setattr(runtime_check.importlib, "import_module", importer)
    report = runtime_check.check_runtime()
    assert not report["ok"]
    assert "WinError 126" in report["dependencies"][failed]["error"]
    assert report["dependencies"]["sounddevice"]["ok"]


@pytest.mark.parametrize("ok,exit_code", [(True, 0), (False, 1)])
def test_cli_emits_machine_readable_result_without_gui(monkeypatch, tmp_path, ok, exit_code):
    monkeypatch.setattr(runtime_check, "check_runtime", lambda: {"ok": ok})
    output = tmp_path / "check.json"
    assert runtime_check.check_main([str(output)]) == exit_code
    assert json.loads(output.read_text()) == {"ok": ok}


def test_cli_preserves_existing_report_and_rejects_relative_path(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("preserve me")
    assert runtime_check.check_main([str(output)]) == 2
    assert output.read_text() == "preserve me"
    assert runtime_check.check_main(["relative.json"]) == 2
    assert runtime_check.check_main([]) == 2


def test_frozen_repair_guidance_uses_installer(monkeypatch):
    import main
    monkeypatch.setattr(main, "missing_packages", ["torch"])
    monkeypatch.setattr(main, "dependency_errors", {"torch": OSError("missing DLL")})
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    message = main.dependency_failure_message()
    assert "free space" in message
    assert "Windows installer" in message
    assert "pip install" not in message


def test_probe_checks_dhaka_zoneinfo_and_tzlocal(monkeypatch):
    monkeypatch.setattr(runtime_check.importlib, "import_module", fake_import)
    report = runtime_check.check_runtime()
    assert report["dependencies"]["tzdata"]["ok"]
    assert report["dependencies"]["tzlocal"]["ok"]


def test_probe_exercises_download_tls_initialization(monkeypatch):
    def broken_tls():
        raise OSError("[WinError 126] missing TLS component")
    def importer(name):
        return SimpleNamespace(configure_native_tls=broken_tls) if name == "native_tls" else fake_import(name)
    monkeypatch.setattr(runtime_check.importlib, "import_module", importer)
    report = runtime_check.check_runtime()
    assert not report["ok"]
    assert "missing TLS component" in report["dependencies"]["native_tls"]["error"]
    assert report["dependencies"]["huggingface_hub"]["ok"]
