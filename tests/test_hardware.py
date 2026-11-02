import json

import pytest

from engines.hardware import record_speed_check


def test_speed_check_appends_without_losing_past_checks_or_unknown_fields(tmp_path):
    path = tmp_path / "checks.json"
    path.write_text(json.dumps({"version": 1, "custom": "keep", "checks": [{"rtf": 2}]}))
    record_speed_check({"rtf": .4}, path)
    data = json.loads(path.read_text())
    assert data["custom"] == "keep" and data["checks"] == [{"rtf": 2}, {"rtf": .4}]
    path.write_text("broken original", encoding="utf-8")
    with pytest.raises(ValueError):
        record_speed_check({"rtf": .5}, path)
    assert path.read_text() == "broken original"
