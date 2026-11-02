"""CPU GGUF translation using the model's embedded structured chat template."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import threading

from engines.cancellation import check_cancelled, current_stop_event
from engines.lid import LATIN_LANGUAGES
from engines.protect import protect, apply_preferred_terms
from engines.types import MtResult


MANIFEST = json.loads((Path(__file__).parent / "data" / "translategemma.json").read_text(encoding="utf-8"))
GEMMA_TERMS_URL = MANIFEST["license_url"]
LANGUAGES = frozenset(MANIFEST["supported_languages"])


class LocalTranslationUnavailable(RuntimeError):
    pass


def configured_model_path():
    from app_config import CONFIG_FILE, read_config
    value = read_config().get("ENGINES", "translategemma_path", fallback="").strip()
    return Path(value).expanduser() if value else CONFIG_FILE.parent / "models" / "translategemma" / MANIFEST["filename"]


def enough_ram():
    import psutil
    return psutil.virtual_memory().total >= 8 * 2**30


def gemma_available(source=None, target=None):
    return (enough_ram() and configured_model_path().is_file()
            and (source is None or source in LANGUAGES)
            and (target is None or target in LANGUAGES))


def download_model(folder, *, accepted_terms=False, on_event=None, manifest=MANIFEST):
    if not accepted_terms:
        raise ValueError("Review and accept the Gemma Terms of Use before downloading.")
    from model_loading import _download_repo_with_progress
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _download_repo_with_progress(manifest["repo"], "TranslateGemma 4B", 0, 0.95, on_event,
                                 revision=manifest["revision"], local_dir=folder,
                                 allow_patterns=[manifest["filename"]])
    path = folder / manifest["filename"]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != manifest["sha256"]:
        raise ValueError("The TranslateGemma download did not match its checksum; the file was preserved.")
    if callable(on_event):
        on_event("model_progress", {"phase": "TranslateGemma download verified", "fraction": 1.0})
    return path


class TranslateGemma:
    name = "translategemma-local"
    requires_network = False

    def __init__(self, model_path=None, *, loader=None, ram_check=enough_ram):
        self.path = Path(model_path) if model_path else configured_model_path()
        self.loader = loader
        self.ram_check = ram_check
        self.model = None
        self.formatter = None
        self.lock = threading.RLock()
        self.warmed = False

    def supports(self, source, target):
        return source in LANGUAGES and target in LANGUAGES and self.ram_check() and self.path.is_file()

    def load(self):
        with self.lock:
            if self.model is not None:
                return self
            if not self.ram_check():
                raise LocalTranslationUnavailable("TranslateGemma needs at least 8 GB RAM. Using the local Lite translator.")
            if not self.path.is_file():
                raise LocalTranslationUnavailable("Download TranslateGemma in Settings before using it offline.")
            import psutil
            from llama_cpp import Llama
            from llama_cpp.llama_chat_format import Jinja2ChatFormatter
            model = (self.loader or Llama)(model_path=str(self.path), n_ctx=2048,
                                          n_threads=psutil.cpu_count(logical=False) or 2,
                                          n_gpu_layers=0, verbose=False)
            template = model.metadata.get("tokenizer.chat_template", "")
            if hashlib.sha256(template.replace("\r\n", "\n").encode("utf-8")).hexdigest() != MANIFEST["template_sha256"]:
                model.close()
                raise LocalTranslationUnavailable("This GGUF does not contain the verified TranslateGemma template.")
            formatter = Jinja2ChatFormatter(template, bos_token="<bos>", eos_token="<eos>")
            self.model, self.formatter = model, formatter
        return self

    @staticmethod
    def _message(text, source, target):
        # Saudi meetings are the primary Arabic locale. Other language choices
        # stay generic, rather than inferring a country from the user's machine.
        return {"role": "user", "content": [{"type": "text", "source_lang_code": "ar-SA" if source == "ar" else source,
                 "target_lang_code": "ar-SA" if target == "ar" else target, "text": text}]}

    def _prompt(self, text, source, target, context, instruction):
        messages = []
        for previous_source, previous_target in context[-2:]:
            messages.extend((self._message(previous_source, source, target),
                             {"role": "assistant", "content": previous_target}))
        marker = "TRANSLITO_CURRENT_TEXT_SENTINEL"
        while marker in text or any(marker in str(message) for message in messages):
            marker += "_"
        messages.append(self._message(marker, source, target))
        prompt = self.formatter(messages=messages).prompt
        text_at = prompt.index(marker)
        # Amend the verified current-user instruction, never the source text or
        # the few-shot examples. System roles are unsupported by TranslateGemma.
        instruction_at = prompt.rfind("Please translate the following", 0, text_at)
        if instruction_at < 0:
            raise LocalTranslationUnavailable("TranslateGemma's translation instruction was not found.")
        prompt = prompt[:instruction_at] + instruction + " " + prompt[instruction_at:]
        return prompt.replace(marker, text, 1)

    def warmup(self):
        self.load()
        with self.lock:
            if not self.warmed:
                prompt = self._prompt("Good morning.", "en", "ar", [], "")
                tokens = self.model.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
                self.model.create_completion(prompt=tokens, max_tokens=1, temperature=0,
                                             stop=["<end_of_turn>", "<eos>"])
                self.warmed = True
        return self

    def translate(self, text, source, target, *, context, glossary):
        check_cancelled()
        if source == target or not text.strip():
            return MtResult(text, self.name)
        if source not in LANGUAGES or target not in LANGUAGES:
            raise LocalTranslationUnavailable("This language pair is not enabled for TranslateGemma.")
        self.load()
        original_text = text
        text = apply_preferred_terms(text, glossary) if source == "en" and target == "ar" else text
        protected = protect(text, "llm", latin=target == "en" and source not in LATIN_LANGUAGES,
                            other_script=source == "en",
                            terms=[term for term, value in glossary.items() if not value])
        instruction = "Keep English words and anything inside ⟦ ⟧ unchanged."
        with self.lock:
            check_cancelled()
            input_tokens = self.model.tokenize(original_text.encode("utf-8"), add_bos=False)
            context = list(context[-2:])
            for attempt in range(2):
                prompt = self._prompt(protected.text, source, target, context, instruction)
                tokens = self.model.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
                while len(tokens) + 1 >= 2048 and context:
                    context.pop(0)
                    prompt = self._prompt(protected.text, source, target, context, instruction)
                    tokens = self.model.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
                maximum = min(max(1, 3 * len(input_tokens)), 2048 - len(tokens) - 1)
                if maximum <= 0:
                    raise LocalTranslationUnavailable("The sentence is too long for the local translation context.")
                from llama_cpp import StoppingCriteriaList
                stop_event = current_stop_event()
                criteria = StoppingCriteriaList([lambda *_: stop_event is not None and stop_event.is_set()])
                result = self.model.create_completion(prompt=tokens, max_tokens=maximum, temperature=0,
                    stop=["<end_of_turn>", "<eos>"], stopping_criteria=criteria)
                check_cancelled()
                output = result["choices"][0]["text"].strip()
                if output and protected.verify(output):
                    for span in protected.spans:
                        output = output.replace(f"⟦{span}⟧", span)
                    return MtResult(output, self.name)
                instruction += " Preserve every marked span exactly; do not transliterate it."
        raise LocalTranslationUnavailable("TranslateGemma did not preserve the protected terms after retry.")


@lru_cache(maxsize=2)
def cached_translator(model_path):
    return TranslateGemma(model_path)
