"""Export catalog metadata for Hugo; does not translate copy or download data."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engines.languages import site_data


def serialized():
    return json.dumps(site_data(), ensure_ascii=False, indent=2) + "\n"


def export(path=None):
    path = Path(path) if path else ROOT / "website/data/languages.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized(), encoding="utf-8")


if __name__ == "__main__":
    if "--check" in sys.argv:
        assert (ROOT / "website/data/languages.json").read_text(encoding="utf-8") == serialized(), "Run tools/site_languages.py"
    else:
        export()
