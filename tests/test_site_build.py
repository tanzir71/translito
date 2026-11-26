"""Build the actual site with the Pages toolchain; never write website/public."""
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import shutil
import subprocess
import tomllib

import pytest

from engines.languages import PRIORITY

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "website"


class Document(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.text = path.read_text(encoding="utf-8")
        self.feed(self.text)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))

    def tags(self, name):
        return [attributes for tag, attributes in self.elements if tag == name]


@pytest.fixture(scope="session")
def built_site(tmp_path_factory):
    local = ROOT / "tools/bin" / ("hugo.exe" if os.name == "nt" else "hugo")
    candidates = [os.environ.get("TRANSLITO_HUGO"), str(local) if local.is_file() else None, shutil.which("hugo")]
    binary = None
    for candidate in filter(None, candidates):
        version = subprocess.run([candidate, "version"], capture_output=True, text=True, check=True).stdout
        if re.search(r"hugo v0\.121\.0[-+].*\+extended\b", version):
            binary = candidate
            break
    assert binary, "Install Hugo 0.121.0 extended in ignored tools/bin, or set TRANSLITO_HUGO."
    folder = tmp_path_factory.mktemp("hugo-v3")
    destination = folder / "site"
    result = subprocess.run([binary, "--source", str(SITE), "--destination", str(destination),
        "--cacheDir", str(folder / "cache"), "--noBuildLock", "--printI18nWarnings"],
        capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, HUGO_RESOURCEDIR=str(folder / "resources")))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MISSING_TRANSLATION" not in result.stdout + result.stderr
    assert not re.search(r"i18n.*(?:WARN|missing)|WARN.*i18n", result.stdout + result.stderr, re.I)
    return destination


@pytest.mark.parametrize("entry", PRIORITY, ids=lambda entry: entry.site_locale)
def test_fourteen_homes_have_language_direction_and_complete_alternates(built_site, entry):
    path = built_site / ("" if entry.site_locale == "en" else entry.site_locale) / "index.html"
    document = Document(path)
    assert document.tags("html")[0]["lang"].casefold() == entry.bcp47.casefold()
    assert document.tags("html")[0]["dir"] == ("rtl" if entry.rtl else "ltr")
    alternates = {tag["hreflang"]: tag["href"] for tag in document.tags("link") if tag.get("rel") == "alternate"}
    assert set(alternates) == {item.bcp47 for item in PRIORITY} | {"x-default"}
    assert alternates["x-default"] == "https://localarabic.com/"
    choices = [tag for tag in document.tags("a") if "data-locale-choice" in tag]
    assert {tag["data-locale-choice"] for tag in choices} == {item.site_locale for item in PRIORITY}
    assert any(tag.get("aria-expanded") == "false" and tag.get("aria-controls") == "locale-menu" for tag in document.tags("button"))
    assert document.tags("details")  # Native no-JavaScript picker remains usable.


def test_locale_configuration_and_draft_review_contract():
    config = tomllib.loads((SITE / "hugo.toml").read_text(encoding="utf-8"))
    assert config["defaultContentLanguage"] == "en"
    assert not config["defaultContentLanguageInSubdir"]
    assert list(config["languages"]) == [entry.site_locale for entry in PRIORITY]
    keys = None
    for entry in PRIORITY:
        assert config["languages"][entry.site_locale]["params"]["reviewed"] is False
        text = (SITE / "i18n" / (entry.site_locale + ".toml")).read_text(encoding="utf-8")
        assert text.splitlines()[0].startswith("# Draft for native review")
        locale = tomllib.loads(text)
        assert all(value["other"].strip() for value in locale.values())
        keys = keys or set(locale)
        assert set(locale) == keys


def test_site_never_claims_fifty_languages_or_redirects_by_browser_language(built_site):
    for path in built_site.rglob("*.html"):
        assert "50+" not in path.read_text(encoding="utf-8")
    script = (SITE / "static/js/main.js").read_text(encoding="utf-8")
    assert "localStorage" in script and 'event.key === "Escape"' in script
    assert 'root.dataset.siteLocale === "en" && root.dataset.home === "true"' in script
    assert "navigator.language" not in script
