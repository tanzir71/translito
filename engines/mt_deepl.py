"""DeepL API Free, XML exclusions and immutable, cached v3 glossaries."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from engines.cloud_http import CloudHttp, provider_key
from engines.mt_cloud import CloudText, MarkupTranslator
from engines.provider import AuthenticationError, ProviderBinding, ProviderError
from engines.usage import LOCAL_RATE, MonthlyQuota, Units


class DeepLTranslator(MarkupTranslator):
    name = "deepl"
    adapter = "deepl"
    endpoint = "https://api-free.deepl.com"

    def __init__(self, credentials, *, http=None, cache_path=None, on_hint=None):
        self.credentials = credentials
        self.http = http or CloudHttp()
        if cache_path is None:
            from app_config import CONFIG_FILE
            cache_path = CONFIG_FILE.parent / "deepl_glossaries.sqlite3"
        self.cache_path = Path(cache_path)
        self.glossary_languages = None
        self.on_hint = on_hint or (lambda _: None)
        self._unsupported_hint = False

    def headers(self):
        key = provider_key(self.credentials, self.name)
        # A paid key can never be sent accidentally from the Free profile.
        if not key.endswith(":fx"):
            raise AuthenticationError()
        return {"Authorization": "DeepL-Auth-Key " + key}

    def markup(self, text):
        return "<text>" + text + "</text>"

    def account_usage(self):
        response = self.http.get(self.endpoint + "/v2/usage", headers=self.headers())
        try:
            count, limit = int(response["character_count"]), int(response["character_limit"])
            if count < 0 or limit < 0:
                raise ValueError()
            return {"used": count, "limit": limit}
        except (TypeError, KeyError, ValueError):
            raise ProviderError() from None

    def _glossary(self, source, target, terms):
        if not terms:
            return None
        if self.glossary_languages is None:
            data = self.http.get(self.endpoint + "/v3/languages", params={"resource": "glossary"},
                                 headers=self.headers())
            try:
                self.glossary_languages = (
                    {row["lang"].lower().split("-")[0] for row in data if row.get("usable_as_source")},
                    {row["lang"].lower().split("-")[0] for row in data if row.get("usable_as_target")})
            except (TypeError, KeyError, AttributeError):
                raise ProviderError() from None
        if source not in self.glossary_languages[0] or target not in self.glossary_languages[1]:
            if not self._unsupported_hint:
                self.on_hint("DeepL does not offer a glossary for this pair. Protected terms and preferred spellings still apply.")
                self._unsupported_hint = True
            return None
        entries = {term: value or term for term, value in terms.items()}
        if any(not isinstance(value, str) or any(c in term + value for c in "\t\r\n")
               for term, value in entries.items()):
            raise ProviderError()
        # Only hashes and app-owned resource IDs are stored. New versions append
        # records; no old local or server glossary is modified/deleted.
        signature = hashlib.sha256(json.dumps([provider_key(self.credentials, self.name), source, target,
                                               sorted(entries.items())], ensure_ascii=True).encode()).hexdigest()
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(sqlite3.connect(self.cache_path, timeout=15)) as connection, connection:
                connection.execute("CREATE TABLE IF NOT EXISTS glossary_records (signature TEXT, resource_id TEXT, created_utc TEXT DEFAULT CURRENT_TIMESTAMP)")
                connection.execute("BEGIN IMMEDIATE")
                found = connection.execute("SELECT resource_id FROM glossary_records WHERE signature = ? ORDER BY rowid DESC LIMIT 1",
                                           (signature,)).fetchone()
                if found:
                    return found[0]
                response = self.http.post(self.endpoint + "/v3/glossaries", headers=self.headers(), json={
                    "name": "Translito " + source + "-" + target + " " + signature[:12],
                    "dictionaries": [{"source_lang": source, "target_lang": target,
                                      "entries": "\n".join(term + "\t" + value for term, value in sorted(entries.items())),
                                      "entries_format": "tsv"}]})
                resource_id = response.get("glossary_id")
                if not isinstance(resource_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", resource_id):
                    raise ProviderError()
                connection.execute("INSERT INTO glossary_records (signature, resource_id) VALUES (?, ?)", (signature, resource_id))
                return resource_id
        except (sqlite3.Error, OSError):
            raise ProviderError() from None

    def request(self, text, source, target, *, context, glossary):
        data = {"text": [text], "source_lang": source.upper(), "target_lang": {"en": "EN-US", "pt": "PT-PT"}.get(target, target.upper()),
                "tag_handling": "xml", "tag_handling_version": "v2", "ignore_tags": ["x"]}
        if context:
            data["context"] = "\n".join(src + "\n" + tgt for src, tgt in context[-2:])
        resource = self._glossary(source, target, glossary)
        if resource:
            data["glossary_id"] = resource
        response = self.http.post(self.endpoint + "/v2/translate", headers=self.headers(), json=data)
        try:
            translated = response["translations"][0]
            count = translated.get("billed_characters")
            usage = Units(characters=count) if isinstance(count, int) and count >= 0 else None
            return CloudText(translated["text"], usage)
        except (TypeError, KeyError, IndexError):
            raise ProviderError() from None


def build(preference, credentials):
    return ProviderBinding(DeepLTranslator(credentials), rate=LOCAL_RATE if preference.account_kind == "free" else None,
                            quota=MonthlyQuota(characters=500_000), monthly_cap=0)
