"""Build the actual site with the Pages toolchain; never write website/public."""
from html.parser import HTMLParser
from pathlib import Path
import os
import json
import hashlib
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
        self.text_parts = []
        self.text = path.read_text(encoding="utf-8")
        self.feed(self.text)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))

    def tags(self, name):
        return [attributes for tag, attributes in self.elements if tag == name]

    def handle_data(self, data):
        self.text_parts.append(data)

    @property
    def plain_text(self):
        return " ".join("".join(self.text_parts).split())


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


def test_english_landing_sections_assets_and_language_links(built_site):
    document = Document(built_site / "index.html")
    sections = [tag["id"] for tag in document.tags("section") if "id" in tag]
    assert sections == ["features", "subtitles", "schedule", "replies", "cost", "settings", "also", "languages", "how", "questions", "download"]
    for image in document.tags("img"):
        assert image["src"].startswith("/")
        assert (built_site / image["src"].lstrip("/")).is_file()
        if image["src"].endswith("-settings.webp"):
            assert image["loading"] == "lazy"
            assert image["width"] == "1200"
    for tag in document.tags("a"):
        if tag.get("href", "").startswith("/languages/"):
            assert (built_site / tag["href"].lstrip("/") / "index.html").is_file()
    for copy in ("Weekly sync is starting", "Subtitles are on, translating into English.",
                 "Mumkin tiid as-sual?", "Mozhete povtorit vopros?", "Kya aap sawal dohra sakte hain?",
                 "The features listed under New on Windows are not in the Mac app."):
        assert copy in document.text
    assert "Windows 1.0.4" not in document.text


def test_supplied_landing_assets_and_svg_roots_remain_unchanged():
    from PIL import Image
    receipt = json.loads((SITE / "data/landing_assets.json").read_text())
    assert (receipt["desktop_width"], receipt["content_width"], receipt["mobile_width"], receipt["mobile_content_width"]) == (1440, 1120, 390, 350)
    assert len(receipt["files"]) == 14
    for name, metadata in receipt["files"].items():
        path = SITE / "static" / name
        assert path.stat().st_size > 0
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]
        if path.suffix == ".svg":
            header = path.read_text().split(">", 1)[0]
            assert float(re.search(r'width="([\d.]+)"', header)[1]) == metadata["width"]
            assert float(re.search(r'height="([\d.]+)"', header)[1]) == metadata["height"]
        else:
            with Image.open(path) as image:
                assert image.size == (metadata["width"], metadata["height"])


def test_subtitle_scene_scales_to_the_desktop_and_mobile_design():
    node = shutil.which("node")
    assert node, "Node is required for the landing JavaScript contract check."
    script = "const fs=require('fs'),vm=require('vm');const c={document:{addEventListener(){}}};vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);console.log(JSON.stringify([c.heroGeometry(1120),c.heroGeometry(350),c.heroGeometry(560,'language')]));"
    result = subprocess.run([node, "-e", script, str(SITE / "static/js/main.js")], capture_output=True, text=True, check=True)
    desktop, mobile, language_page = json.loads(result.stdout)
    assert desktop == dict(scale=1, left=0, top=0)
    assert mobile["scale"] == pytest.approx(396.46 / 1120)
    assert mobile["left"] == -46 and mobile["top"] == -102
    assert language_page["scale"] == pytest.approx(918.974 / 1120)
    assert language_page["left"] == -179 and language_page["top"] == -188


@pytest.mark.parametrize("entry", PRIORITY, ids=lambda entry: entry.site_locale)
def test_every_home_has_complete_localized_sections_examples_and_metadata(built_site, entry):
    folder = built_site / ("" if entry.code == "en" else entry.site_locale)
    document = Document(folder / "index.html")
    strings = tomllib.loads((SITE / "i18n" / (entry.site_locale + ".toml")).read_text(encoding="utf-8"))
    english = tomllib.loads((SITE / "i18n/en.toml").read_text(encoding="utf-8"))
    shared_words = {("de", "navDownload"), ("fr", "navMenu"), ("fr", "faqTitle"),
                    ("nl", "translitoIn"), ("nl", "navMenu"), ("pl", "navMenu"), ("pt", "navMenu")}
    for key, value in strings.items():
        if entry.code != "en" and key != "heroCurrent" and (entry.code, key) not in shared_words:
            assert value["other"] != english[key]["other"], (entry.code, key)
    for key in ("heroTitle", "heroPrevious", "heroCurrent", "overviewTitle", "feature1Title", "feature2Title",
                "feature3Title", "feature4Title", "feature5Title", "howTitle", "downloadTitle", "faqTitle"):
        assert strings[key]["other"] in document.plain_text, (entry.code, key)
    assert strings["seoTitle"]["other"] in document.plain_text
    descriptions = [tag["content"] for tag in document.tags("meta") if tag.get("name") == "description"]
    assert descriptions == [strings["description"]["other"]]
    assert "Weekly sync is starting" in document.plain_text
    assert "Subtitles are on, translating into English." in document.plain_text
    current = [tag for tag in document.tags("p") if tag.get("class") == "current"]
    assert len(current) == 1
    assert current[0]["lang"] == "en-US"
    assert current[0]["dir"] == "ltr"
    if entry.code != "en":
        assert strings["heroCurrent"]["other"] == english["heroCurrent"]["other"]
    rows = [tag for tag in document.tags("div") if tag.get("class", "").startswith("reply-row")]
    assert len(rows) == (4 if entry.code == "en" else 3)
    if entry.code != "en":
        for index in range(1, 4):
            assert strings[f"replyMeaning{index}"]["other"] in document.plain_text
        assert "Yes, Thursday is fine" in document.plain_text


def test_reference_native_questions_are_shown_with_english_translations():
    expected = {
        "ar": ("تابع كل اجتماع بلغتك.", "متى يمكننا تسليم النسخة الأولى؟", "When can we deliver the first version?"),
        "ja": ("すべての会議を、あなたの言語で。", "最初のバージョンはいつ納品できますか？", "When can we deliver the first version?"),
    }
    for code, values in expected.items():
        strings = tomllib.loads((SITE / "i18n" / (code + ".toml")).read_text(encoding="utf-8"))
        assert tuple(strings[key]["other"] for key in ("heroTitle", "heroPrevious", "heroCurrent")) == values


@pytest.mark.parametrize("entry", [item for item in PRIORITY if item.slug], ids=lambda entry: entry.slug)
def test_thirteen_english_language_pages_have_native_to_english_examples(built_site, entry):
    from tools.site_languages import language_page_source
    from engines.replies import parse_replies, phrasebook
    document = Document(built_site / "languages" / entry.slug / "index.html")
    data = json.loads((SITE / "data/language_pages" / (entry.slug + ".json")).read_text(encoding="utf-8"))
    source = SITE / "content/languages" / (entry.slug + ".md")
    assert source.read_text(encoding="utf-8") == language_page_source(entry)
    assert data["code"] == entry.code and data["reviewed"] is False and data["draft_for_native_review"] is True
    assert document.tags("html")[0]["lang"] == "en-US"
    assert document.tags("html")[0]["dir"] == "ltr"
    name = entry.english_name
    assert f"Translito for {name}: live {name} and English meeting subtitles" in document.plain_text
    description = (f"Live subtitles between {name} and English over Zoom, Teams or Meet on Windows. Short replies in {name}" +
        (", written in English letters" if entry.romanize_replies else "") +
        ". Free on your PC, with optional pay-as-you-go cloud engines.")
    assert any(tag.get("name") == "description" and tag["content"] == description for tag in document.tags("meta"))
    assert [tag["id"] for tag in document.tags("section") if "id" in tag] == ["examples", "language-replies", "language-quality", "other-languages", "download"]
    assert len(data["samples"]) == 3 and any("API" in row["native"] for row in data["samples"])
    for row in data["samples"]:
        assert row["native"] in document.plain_text and row["english"] in document.plain_text
    parsed = parse_replies({"replies": data["replies"]})
    assert len(parsed) == 3
    assert parsed[-1].native == phrasebook(entry.code)[-1].native
    for reply in parsed:
        assert reply.spoken in document.plain_text and reply.meaning in document.plain_text
        assert len(reply.spoken.split()) <= 8 and reply.romanized.isascii()
    assert "Arabic to English is the pair we measure on every release." in document.plain_text
    links = [tag for tag in document.tags("a") if tag.get("class") == "language-row" and tag.get("aria-current") == "page"]
    assert len(links) == 1 and links[0]["href"] == f"/languages/{entry.slug}/"
    originals = [tag for tag in document.tags("p") if tag.get("class") == "previous"]
    translated = [tag for tag in document.tags("p") if tag.get("class") == "current"]
    assert originals[0]["lang"] == entry.bcp47 and translated[0]["lang"] == "en"


def test_language_pages_exist_only_for_the_thirteen_priority_languages(built_site):
    expected = {item.slug for item in PRIORITY if item.slug}
    assert {path.parent.name for path in (built_site / "languages").glob("*/index.html")} == expected
    assert {path.stem for path in (SITE / "data/language_pages").glob("*.json")} == expected


def test_spanish_language_page_uses_the_reference_examples():
    data = json.loads((SITE / "data/language_pages/spanish.json").read_text(encoding="utf-8"))
    assert [row["native"] for row in data["samples"]] == ["Vamos a revisar el presupuesto del trimestre.",
        "El deployment se retrasó dos días por un problema con la API.", "¿Podemos mantener la entrega del jueves?"]
    assert [row["native"] for row in data["replies"]] == ["Sí, el jueves está bien", "Deme dos días y le confirmo", "¿Puede repetir la pregunta?"]
