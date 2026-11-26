"""Export catalog metadata for Hugo; does not translate copy or download data."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engines.languages import site_data, PRIORITY


def serialized():
    return json.dumps(site_data(), ensure_ascii=False, indent=2) + "\n"


def export(path=None):
    path = Path(path) if path else ROOT / "website/data/languages.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized(), encoding="utf-8")


def language_page_source(entry):
    name = entry.english_name
    title = f"Translito for {name}: live {name} and English meeting subtitles"
    description = (f"Live subtitles between {name} and English over Zoom, Teams or Meet on Windows. "
        f"Short replies in {name}" + (", written in English letters" if entry.romanize_replies else "") +
        ". Free on your PC, with optional pay-as-you-go cloud engines.")
    return ("+++\ntitle = " + json.dumps(title) + "\ndescription = " + json.dumps(description) +
        '\nlayout = "language"\nlanguage = ' + json.dumps(entry.code) + "\n+++\n")


def export_pages(*, check=False):
    folder = ROOT / "website/content/languages"
    folder.mkdir(parents=True, exist_ok=True)
    expected = {entry.slug for entry in PRIORITY if entry.slug}
    data_folder = ROOT / "website/data/language_pages"
    assert {path.stem for path in data_folder.glob("*.json")} == expected, "Need one example data file per priority language"
    for entry in PRIORITY:
        if not entry.slug:
            continue
        data = json.loads((data_folder / (entry.slug + ".json")).read_text(encoding="utf-8"))
        assert data["code"] == entry.code and data["slug"] == entry.slug
        path = folder / (entry.slug + ".md")
        if check:
            assert path.read_text(encoding="utf-8") == language_page_source(entry), "Run tools/site_languages.py"
        else:
            path.write_text(language_page_source(entry), encoding="utf-8")


if __name__ == "__main__":
    if "--check" in sys.argv:
        assert (ROOT / "website/data/languages.json").read_text(encoding="utf-8") == serialized(), "Run tools/site_languages.py"
        export_pages(check=True)
    else:
        export()
        export_pages()
