"""Route and setup intent tests use fake files and never fetch model weights."""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from engines.downloads import DownloadJob, DownloadManager
from engines.model_files import Missing, Ready
from engines.model_library import ModelSpec
from engines.session_state import normalized_settings, readiness, resolve_plan, translation_resources
from engines.settings import EngineSettings, ProviderSettings


def cloud(name="soniox", **kw):
    pref = ProviderSettings(enabled=True, monthly_cap=Decimal(5), account_kind="paid", tested_signature="a" * 64)
    return EngineSettings(engine_choice="cloud", monthly_cap=Decimal(5), default_asr_provider=name,
                          providers={name: pref}, **kw)


def available(spec):
    return Ready(Path("fake"))


def test_native_cloud_needs_filter_but_not_optional_lite():
    plan = resolve_plan(cloud(), ("ar", "en"), inspect=lambda spec: available(spec) if "whisper" in spec.repo.lower() else Missing())
    assert plan.asr == plan.mt == "soniox"
    assert not plan.required_resources and plan.backup_resources
    assert readiness(plan).can_start
    assert plan.whisper_model == "openai/whisper-base"


def test_fresh_local_prepares_base_and_current_pair_only():
    plan = resolve_plan(EngineSettings(engine_choice="local"), ("ar", "en"), inspect=lambda _: Missing())
    assert plan.whisper_model == "openai/whisper-base"
    assert any("whisper" in s.repo.lower() for s in plan.required_resources)
    assert not any("small" in s.repo.lower() or "gemma" in s.repo.lower() for s in plan.required_resources)
    assert plan.asr == plan.mt == "local" and not plan.backup_resources
    assert readiness(plan).phase == "preparing"


def test_speechmatics_requires_local_translation_when_no_text_cloud():
    plan = resolve_plan(cloud("speechmatics"), ("es", "en"), inspect=lambda spec: available(spec) if "whisper" in spec.repo.lower() else Missing())
    assert plan.asr == "speechmatics" and plan.mt == "local"
    assert plan.required_resources and not readiness(plan).can_start


def test_soniox_can_use_an_explicit_local_translator():
    from engines.streaming_protocols import SonioxProtocol
    plan = resolve_plan(cloud(default_mt_provider="local"), ("ar", "en"), inspect=available)
    assert plan.asr == "soniox" and plan.mt == "local" and not plan.cloud_translation
    protocol = SonioxProtocol(languages=("ar", "en"), native_translation=False)
    assert "translation" not in protocol.start()
    assert "translation_terms" not in protocol.start()["context"]


@pytest.mark.parametrize("blocked,failure,credentials,action", [
    (False, "", {"soniox": False}, "connect"),
    (True, "", None, "privacy"),
    (False, "key rejected", None, "connect"),
])
def test_stop_policy_has_specific_setup_action(blocked, failure, credentials, action):
    plan = resolve_plan(cloud(fallback_on_budget="stop"), ("ar", "en"), inspect=available,
                        block_all=blocked, failure=failure, credentials=credentials)
    assert readiness(plan).action == action


def test_cloud_failure_falls_back_without_overwriting_preference():
    settings = cloud()
    plan = resolve_plan(settings, ("ar", "en"), inspect=available, failure="couldn't be reached")
    assert plan.preferred_engine == "cloud" and plan.asr == plan.mt == "local"
    assert readiness(plan).can_start and settings.engine_choice == "cloud"


def test_explicit_choice_overrides_old_profile_and_same_language_blocks():
    settings = EngineSettings(profile="offline", engine_choice="cloud")
    assert normalized_settings(settings).profile == "custom"
    assert readiness(resolve_plan(settings, ("en", "en"), inspect=available)).action == "languages"


def test_budget_and_pair_override_are_resolved_for_the_actual_pair():
    settings = replace(cloud(), pair_overrides={"es_en": {"asr_provider": "local", "mt_provider": "local"}})
    assert resolve_plan(settings, ("es", "en"), mode="speak", inspect=available).asr == "local"
    plan = resolve_plan(replace(settings, monthly_cap=Decimal(0), fallback_on_budget="stop"), ("ar", "en"), inspect=available)
    assert readiness(plan).action == "budget"


def test_cached_pair_specific_speech_model_overrides_the_main_preference():
    settings = EngineSettings(engine_choice="local", pair_overrides={"es_en": {
        "asr_provider":"local", "asr_model":"openai/whisper-large-v3-turbo"}})
    plan = resolve_plan(settings, ("es", "en"), preferred_whisper="openai/whisper-small", inspect=available)
    assert plan.whisper_model == "openai/whisper-large-v3-turbo"


def test_ready_cached_quality_translator_does_not_force_an_extra_lite_download(monkeypatch):
    monkeypatch.setattr("engines.mt_translategemma.enough_ram", lambda: True)
    inspect = lambda spec: available(spec) if spec.format == "gguf" or "whisper" in spec.repo.lower() else Missing()
    plan = resolve_plan(EngineSettings(engine_choice="local"), ("ar", "en"), inspect=inspect)
    assert plan.translation_model == "translategemma:ar:en"
    assert not plan.required_resources and plan.local_ready
    explicit_lite = EngineSettings(engine_choice="local", default_mt_provider="local", default_mt_model="opus")
    assert resolve_plan(explicit_lite, ("ar", "en"), inspect=inspect).required_resources


def spec(tmp_path, name):
    return ModelSpec(name, name, "Translation", "fake/" + name, "transformers", tmp_path / name, expected_size=100)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    import engines.model_files
    monkeypatch.setattr(engines.model_files, "inspect_model", lambda _: Missing())
    return DownloadManager(directory=tmp_path / "jobs", disk_usage=lambda _: SimpleNamespace(free=10**12))


def test_language_switch_pauses_old_auto_reuses_partial_and_prioritizes_new_pair(manager, tmp_path):
    base, ar, es = (spec(tmp_path, n) for n in ("base", "ar-en", "es-en"))
    manager.reconcile_setup((base, ar), context="ar → en")
    old = next(j for j in manager.jobs if j.repo == ar.repo)
    old.bytes, old.total = 40, 100
    manager.active, old.state = old, "Downloading"
    manager.reconcile_setup((base, es), context="es → en")
    assert old.state == "Paused" and old.pause_reason == "superseded" and old.bytes == 40
    assert len([j for j in manager.jobs if j.repo == base.repo]) == 1
    assert next(j for j in manager.jobs if j.repo == es.repo).priority == 0
    manager.reconcile_setup((base, ar), context="ar → en")
    assert old.state == "Queued" and old.bytes == 40
    assert len([j for j in manager.jobs if j.repo == ar.repo]) == 1


@pytest.mark.parametrize("action,state", [("pause", "Paused"), ("cancel", "Cancelled")])
def test_user_pause_or_cancel_survives_switch_and_restart(manager, tmp_path, action, state):
    ar, es = spec(tmp_path, "ar-en"), spec(tmp_path, "es-en")
    manager.reconcile_setup((ar,))
    job = manager.jobs[0]
    getattr(manager, action)(job)
    for _ in range(3):
        manager.reconcile_setup((es,))
        manager.reconcile_setup((ar,))
    assert job.state == state
    restarted = DownloadManager(directory=manager.directory)
    restarted.reconcile_setup((ar,))
    same = next(j for j in restarted.jobs if j.repo == ar.repo)
    assert same.state == state
    assert readiness(resolve_plan(EngineSettings(engine_choice="local"), ("ar", "en"), inspect=available)).can_start
    restarted.resume(same)
    assert same.state == "Queued"


def test_new_required_resource_preempts_automatic_backup_not_manual_work(manager, tmp_path):
    backup, required = spec(tmp_path, "backup"), spec(tmp_path, "required")
    manager.reconcile_setup((), (backup,))
    old = manager.jobs[0]
    manager.active, old.state = old, "Downloading"
    manager.reconcile_setup((required,), (backup,))
    assert manager.active is None and old.state == "Queued" and old.priority == 20
    new = next(j for j in manager.jobs if j.repo == required.repo)
    assert new.priority < old.priority
    old.origin, old.state, manager.active = "manual", "Downloading", old
    manager.reconcile_setup((required,), (backup,))
    assert manager.active is old


def test_already_queued_manual_resource_can_be_prioritized_without_resuming_user_pauses(manager, tmp_path):
    required, backup = spec(tmp_path, "manual-required"), spec(tmp_path, "backup")
    manual = manager.enqueue_model(required)
    manager.reconcile_setup((required,), (backup,))
    assert manual.origin == "manual" and manual.priority == 0
    assert next(j for j in manager.jobs if j.repo == backup.repo).priority == 20
    manager.pause(manual)
    manager.reconcile_setup((required,), (backup,))
    assert manual.state == "Paused"


def test_network_block_preserves_intent(manager, tmp_path):
    required = spec(tmp_path, "required")
    manager.reconcile_setup((required,))
    job = manager.jobs[0]
    manager.block_network()
    manager.blocked = lambda: True
    manager.reconcile_setup((required,))
    assert job.state == "Paused" and job.pause_reason == "blocked"
    with pytest.raises(ValueError):
        manager.resume(job)
    manager.blocked = lambda: False
    manager.reconcile_setup((required,))
    assert job.state == "Queued"


def test_paused_required_download_offers_resume_instead_of_reconfiguration(tmp_path):
    settings = EngineSettings(engine_choice="local")
    plan = resolve_plan(settings, ("ar", "en"), inspect=lambda _: Missing())
    resource = plan.required_resources[0]
    job = DownloadJob("one", resource.repo, resource.title, str(tmp_path), state="Paused")
    assert readiness(plan, jobs=[job]).action == "resume"


def test_shared_translation_pivot_is_deduplicated(manager):
    _, first = translation_resources("ar", "es")
    _, second = translation_resources("ar", "fr")
    manager.reconcile_setup(first)
    manager.reconcile_setup(second)
    assert len({j.repo for j in manager.jobs}) == len(manager.jobs)


def test_missing_files_are_not_treated_as_ready_from_an_old_queue_record(manager, tmp_path):
    required = spec(tmp_path, "removed")
    manager.reconcile_setup((required,))
    old = manager.jobs[0]
    old.state = "Ready"
    manager.reconcile_setup((required,))
    assert len(manager.jobs) == 2 and manager.jobs[-1].state == "Queued"
