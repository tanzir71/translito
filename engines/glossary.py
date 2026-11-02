import json
import os
from pathlib import Path
import re
import tempfile


DEFAULT_TERMS = Path(__file__).parent / "data" / "glossary.json"


class Glossary:
    def __init__(self, path=None, defaults_path=DEFAULT_TERMS, *, read_only=False):
        if path is None:
            from app_config import CONFIG_FILE
            path = CONFIG_FILE.parent / "glossary.json"
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8-sig")) if self.path.exists() else {
            "version": 1, "terms": []}
        if not isinstance(self.data, dict) or not isinstance(self.data.get("terms"), list):
            raise ValueError("Glossary is invalid; the existing file was preserved")
        self._validate(self.data["terms"])
        defaults = json.loads(Path(defaults_path).read_text(encoding="utf-8"))
        self._validate(defaults)
        present = {term["english"].casefold() for term in self.data["terms"]}
        added = [term for term in defaults if term["english"].casefold() not in present]
        if added:
            self.data["terms"].extend(added)
            if not read_only:
                self.save()

    @staticmethod
    def _validate(terms):
        for term in terms:
            if not isinstance(term, dict) or not isinstance(term.get("english"), str) or not term["english"].strip():
                raise ValueError("Each glossary term needs an English spelling")
            if not isinstance(term.get("spellings", []), list) or any(
                    not isinstance(x, str) for x in term.get("spellings", [])):
                raise ValueError("Glossary spellings must be a list of strings")

    @property
    def terms(self):
        return [term for term in self.data["terms"] if not term.get("disabled", False)]

    def save(self):
        self._validate(self.data["terms"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             delete=False) as handle:
                temp_path = Path(handle.name)
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(self.path)
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)

    def restore_english(self, text):
        aliases = {alias: term["english"] for term in self.terms
                   for alias in term.get("spellings", []) if alias}
        if not aliases:
            return text, 0
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(
            re.escape(x) for x in sorted(aliases, key=len, reverse=True)) + r")(?!\w)")
        return pattern.subn(lambda match: aliases[match[0]], text)

    def hotwords(self):
        return ", ".join(term["english"] for term in self.terms)

    def translations(self):
        return {term["english"]: term.get("arabic_translation", "") for term in self.terms}
