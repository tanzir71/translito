"""Verified Marian pairs, English pivoting and a Transformers 4/5 MT adapter."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import threading

from engines.cancellation import check_cancelled, current_stop_event
from engines.protect import translate_opus, apply_preferred_terms
from engines.types import MtResult


_MANIFEST = json.loads((Path(__file__).parent / "data" / "opus_pairs.json").read_text(encoding="utf-8"))
KNOWN_PAIRS = {(entry["source"], entry["target"]): entry["repo"] for entry in _MANIFEST["pairs"]}


class UnsupportedPairError(ValueError):
    pass


@dataclass(frozen=True)
class LocalMtPlan:
    source: str
    target: str
    repos: tuple[str, ...]

    @property
    def model_id(self):
        return "|".join(self.repos) if self.repos else f"identity:{self.source}"


@lru_cache(maxsize=256)
def _repo_exists(repo, offline):
    from huggingface_hub import HfApi, try_to_load_from_cache
    from huggingface_hub.errors import RepositoryNotFoundError
    cached = try_to_load_from_cache(repo, "config.json")
    if isinstance(cached, str) and Path(cached).is_file():
        return True
    if repo in KNOWN_PAIRS.values():
        return True
    if offline:
        return False
    try:
        HfApi(token=False).model_info(repo, timeout=8)
        return True
    except RepositoryNotFoundError:
        return False
    # Network/auth/timeouts propagate; do not cache them as unsupported pairs.


def resolve_local_mt(source, target, *, offline=True, repo_exists=None):
    if source == target:
        return LocalMtPlan(source, target, ())
    if not re.fullmatch(r"[a-z]{2,3}", source) or not re.fullmatch(r"[a-z]{2,3}", target):
        raise UnsupportedPairError("Use ISO language codes for local translation")
    exists = repo_exists or (lambda repo: _repo_exists(repo, offline))
    direct = f"Helsinki-NLP/opus-mt-{source}-{target}"
    if exists(direct):
        return LocalMtPlan(source, target, (direct,))
    if source != "en" and target != "en":
        pivot = (f"Helsinki-NLP/opus-mt-{source}-en", f"Helsinki-NLP/opus-mt-en-{target}")
        if all(exists(repo) for repo in pivot):
            return LocalMtPlan(source, target, pivot)
    raise UnsupportedPairError(
        f"{source} → {target}: This pair needs TranslateGemma or a cloud translator.")


class LocalOpusPipeline:
    """Retain the legacy callable API without the removed translation pipeline.

    Direct AutoModel/AutoTokenizer calls also pass local_files_only explicitly;
    a cached Offline session never needs an HTTP metadata lookup.
    """
    name = "opus-mt"
    requires_network = False

    def __init__(self, model_id, *, device=-1, offline_only=False):
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self.model_id = model_id
        self.steps = []
        self.lock = threading.Lock()
        self.device = "cpu" if device == -1 else f"cuda:{device}"
        if model_id.startswith("identity:"):
            self.tokenizer = None
            return
        for repo in model_id.split("|"):
            tokenizer = AutoTokenizer.from_pretrained(repo, local_files_only=offline_only, token=False)
            model = AutoModelForSeq2SeqLM.from_pretrained(repo, local_files_only=offline_only, token=False)
            model.to(self.device).eval()
            self.steps.append((tokenizer, model))
        self.tokenizer = self.steps[0][0]

    def __call__(self, text, **kwargs):
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        truncation = kwargs.pop("truncation", True)
        event = current_stop_event()
        if event is not None and "stopping_criteria" not in kwargs:
            class Cancelled(StoppingCriteria):
                def __call__(self, input_ids, scores, **kwargs):
                    return event.is_set()
            kwargs["stopping_criteria"] = StoppingCriteriaList([Cancelled()])
        with self.lock:
            check_cancelled()
            for tokenizer, model in self.steps:
                encoded = tokenizer(text, return_tensors="pt", truncation=truncation, max_length=512)
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                with torch.inference_mode():
                    output = model.generate(**encoded, **kwargs)
                check_cancelled()
                text = tokenizer.batch_decode(output, skip_special_tokens=True)[0].strip()
        return [{"translation_text": text}]


class OpusTranslator:
    name = "opus-mt"
    requires_network = False

    def __init__(self, *, offline_only=True, device=-1, on_hint=None, loader=LocalOpusPipeline):
        self.offline_only = offline_only
        self.device = device
        self.on_hint = on_hint
        self.loader = loader
        self.models = {}

    def supports(self, source, target):
        try:
            resolve_local_mt(source, target, offline=self.offline_only)
            return True
        except UnsupportedPairError:
            return False

    def preload(self, source, target):
        plan = resolve_local_mt(source, target, offline=self.offline_only)
        if plan.model_id not in self.models:
            self.models[plan.model_id] = self.loader(plan.model_id, device=self.device,
                                                     offline_only=self.offline_only)
        return self.models[plan.model_id]

    def translate(self, text, source, target, *, context, glossary):
        check_cancelled()
        if source == target:
            return MtResult(text, self.name)
        model = self.preload(source, target)

        def decode(value):
            tokenizer = getattr(model, "tokenizer", None)
            tokens = len(tokenizer.encode(value)) if tokenizer else max(1, len(value.split()) * 2)
            return model(value, num_beams=4, max_new_tokens=max(32, min(512, 3 * tokens)),
                         do_sample=False, truncation=True)[0]["translation_text"]

        # Arabic/Persian/etc. → English: protect Latin spans. English → Arabic:
        # keep existing Arabic runs plus explicitly selected glossary terms.
        text = apply_preferred_terms(text, glossary) if source == "en" else text
        translated = translate_opus(text, decode, latin=target == "en", other_script=source == "en",
                                    terms=[term for term, value in glossary.items() if not value], on_hint=self.on_hint)
        return MtResult(translated, self.name)
