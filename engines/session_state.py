"""Pure session/resource policy shared by desktop setup and session admission."""
from dataclasses import dataclass, replace
from decimal import Decimal

from engines.model_files import Ready, inspect_model, whisper_spec


@dataclass(frozen=True)
class Blocker:
    reason: str
    action: str
    message: str


@dataclass(frozen=True)
class SessionPlan:
    mode: str
    pair: tuple
    preferred_engine: str
    asr: str
    mt: str
    whisper_model: str
    translation_model: str
    required_resources: tuple = ()
    backup_resources: tuple = ()
    local_ready: bool = False
    cloud_reason: str = ""
    blockers: tuple = ()

    @property
    def cloud_translation(self):
        return self.mt != "local"

    @property
    def engine(self):
        from engines.cloud_connect import TITLES
        if self.asr == self.mt == "local":
            return "On this PC"
        if self.asr == self.mt:
            return TITLES.get(self.asr, self.asr)
        return f"{TITLES.get(self.asr, 'On this PC')} + {TITLES.get(self.mt, 'translation on this PC')}"


@dataclass(frozen=True)
class ReadinessState:
    phase: str
    message: str
    action: str = ""
    can_start: bool = False


def normalized_settings(settings):
    """An explicit engine choice wins over the obsolete profile selector."""
    choice = settings.engine_choice or {"offline": "local", "custom": "cloud",
        "live-preview": "cloud", "booster": "cloud"}.get(settings.profile, "free")
    profile = {"local": "offline", "cloud": "custom", "free": "free"}[choice]
    return replace(settings, engine_choice=choice, profile=profile)


def provider_problem(settings, name, pair, factories, *, usage=None, credentials=None):
    factory = next((f for f in factories if f.name == name), None)
    if factory is None or factory.unavailable_reason(*pair):
        return Blocker("unsupported", "engine", "The selected provider or model does not support this language pair.")
    pref = settings.provider(name)
    if factory.training_required and not pref.training_consent:
        return Blocker("consent", "connect", f"Review {factory.title} data settings before connecting.")
    defaults = settings.resolve(*pair)
    model = defaults.get(f"default_{'mt' if factory.kind == 'mt' else 'asr'}_model")
    if model and defaults.get(f"default_{'mt' if factory.kind == 'mt' else 'asr'}_provider") == name and factory.models and model not in factory.models:
        return Blocker("model", "engine", "Choose a supported provider model.")
    if not pref.enabled or not pref.tested_signature or (credentials is not None and credentials.get(name) is False):
        return Blocker("auth", "connect", f"Connect {factory.title} to use this route.")
    if pref.account_kind == "paid":
        if settings.engine_choice == "free":
            return Blocker("tier", "engine", "Choose a free provider or select Cloud, pay as you go.")
        if settings.monthly_cap <= 0 or pref.monthly_cap <= 0:
            return Blocker("budget", "budget", "Set a monthly budget to use cloud.")
        providers = (usage or {}).get("providers", {})
        total = sum((Decimal(str(v.get("estimated_usd", 0))) for v in providers.values()), Decimal(0))
        spent = Decimal(str(providers.get(name, {}).get("estimated_usd", 0)))
        if total >= settings.monthly_cap or spent >= pref.monthly_cap:
            return Blocker("budget", "budget", "The monthly cloud budget is used up.")
    return None


def translation_resources(source, target):
    from engines.mt_local import resolve_local_mt
    from engines.model_library import ModelSpec
    plan = resolve_local_mt(source, target, offline=True)
    return plan, tuple(ModelSpec(repo, f"Lite translation · {source} → {target}", "Translation", repo, "transformers")
                       for repo in plan.repos)


def resolve_plan(settings, pair, *, mode="listen", preferred_whisper="openai/whisper-small",
                 block_all=False, usage=None, credentials=None, failure="", inspect=inspect_model, factories=None):
    from engines.registry import provider_factories
    from engines.mt_local import UnsupportedPairError
    settings = normalized_settings(settings)
    pair = tuple(pair)
    factories = tuple(provider_factories() if factories is None else factories)
    defaults = settings.resolve(*pair)
    choice = settings.engine_choice
    if defaults["default_asr_provider"] == "local" and defaults["default_asr_model"]:
        preferred_whisper = defaults["default_asr_model"]
    if pair[0] == pair[1]:
        return SessionPlan(mode, pair, choice, "local", "local", preferred_whisper, "", blockers=(
            Blocker("languages", "languages", "Choose different spoken and target languages."),))

    requested = defaults["default_asr_provider"] or ("soniox" if choice == "cloud" else "local")
    mt_requested = defaults["default_mt_provider"]
    if choice == "free" and not defaults["default_asr_provider"]:
        requested = next((f.name for f in factories if f.kind == "asr"
            and settings.provider(f.name).account_kind != "paid" and not provider_problem(
                settings, f.name, pair, factories, usage=usage, credentials=credentials)), "local")
    issue = None
    if choice != "local" and requested != "local":
        issue = (Blocker("network", "privacy", "Internet is blocked.") if block_all else
                 Blocker("auth" if failure == "key rejected" else "network", "connect" if failure == "key rejected" else "retry", failure)
                 if failure else provider_problem(settings, requested, pair, factories, usage=usage, credentials=credentials))
    asr = requested if choice != "local" and not issue and not block_all else "local"
    if choice == "local":
        asr = "local"
    mt = "soniox" if asr == "soniox" and mt_requested in {"", "soniox"} else "local"
    mt_issue = None
    candidates = [mt_requested] if mt_requested else [f.name for f in factories if f.kind == "mt"]
    if choice != "local" and not block_all and not issue and mt != "soniox":
        for name in candidates:
            problem = provider_problem(settings, name, pair, factories, usage=usage, credentials=credentials) if name and name != "local" else None
            if mt_requested and problem:
                mt_issue = problem
            if name and name != "local" and not problem:
                mt = name
                break

    # A cloud speech filter has a separate, small default; a preferred large
    # local upgrade must not gate an otherwise usable cloud route.
    speech_order = ([preferred_whisper, "openai/whisper-small", "openai/whisper-base", "openai/whisper-large-v3-turbo"]
                    if asr == "local" else ["openai/whisper-base", "openai/whisper-small", preferred_whisper, "openai/whisper-large-v3-turbo"])
    speech = next((model for model in dict.fromkeys(speech_order) if isinstance(inspect(whisper_spec(model)), Ready)),
                  "openai/whisper-base")
    speech_missing = () if isinstance(inspect(whisper_spec(speech)), Ready) else (whisper_spec(speech),)
    local_specs, mt_plan, local_issue = (), None, None
    try:
        mt_plan, local_specs = translation_resources(*pair)
    except UnsupportedPairError:
        local_issue = Blocker("translation", "engine", "Lite translation is unavailable for this pair. Choose cloud or set up a supported local translator.")
    local_missing = tuple(spec for spec in local_specs if not isinstance(inspect(spec), Ready))
    translation = f"cloud:{pair[0]}:{pair[1]}" if mt != "local" else (mt_plan.model_id if mt_plan else "")
    model_issue = None
    if defaults["default_mt_provider"] != "local" or defaults["default_mt_model"] != "opus":
        from engines.mt_translategemma import MANIFEST, LANGUAGES, configured_model_path, enough_ram
        from engines.model_library import ModelSpec
        gemma = ModelSpec("gemma", "TranslateGemma", "Translation", MANIFEST["repo"], "gguf",
                          configured_model_path(), "gemma", MANIFEST["bytes"])
        if all(code in LANGUAGES for code in pair) and enough_ram() and isinstance(inspect(gemma), Ready):
            local_specs, local_missing, local_issue = (), (), None
            if mt == "local":
                translation = f"translategemma:{pair[0]}:{pair[1]}"
        elif defaults["default_mt_model"] == "translategemma" and mt == "local":
            model_issue = Blocker("model", "models", "Finish TranslateGemma setup in Models or choose Lite translation.")
    local_ready = not speech_missing and not local_missing and local_issue is None
    blockers = []
    if model_issue:
        blockers.append(model_issue)
    if mt_issue and (settings.fallback_on_budget == "stop" or mt_issue.reason in {"auth", "model", "consent", "unsupported"}):
        blockers.append(mt_issue)
    if issue and (settings.fallback_on_budget == "stop" or (issue.reason in {"auth", "tier"} and not failure)):
        blockers.append(issue)
    if mt == "local" and local_issue:
        blockers.append(local_issue)
    required = speech_missing + (local_missing if mt == "local" else ())
    backup = local_missing if mt != "local" and local_issue is None and settings.fallback_on_budget == "local" else ()
    return SessionPlan(mode, pair, choice, asr, mt, speech, translation, required, backup,
                       local_ready, issue.message if issue else mt_issue.message if mt_issue else "", tuple(blockers))


def readiness(plan, *, jobs=(), blocked=False):
    if plan.blockers:
        first = plan.blockers[0]
        return ReadinessState("setup_required", first.message, first.action)
    for spec in plan.required_resources:
        job = next((job for job in reversed(tuple(jobs)) if job.repo == spec.repo), None)
        if blocked:
            return ReadinessState("setup_required", "Allow internet access to finish model setup.", "privacy")
        if job is not None and job.state in {"Paused", "Cancelled"}:
            return ReadinessState("setup_required", f"Setup paused · {spec.title}", "resume")
    if plan.required_resources:
        title = "Preparing speech filter" if plan.asr != "local" else "Preparing local setup"
        return ReadinessState("preparing", title, "models")
    return ReadinessState("ready", plan.cloud_reason or f"Ready · {plan.engine}", can_start=True)
