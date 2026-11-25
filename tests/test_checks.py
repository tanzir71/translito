from decimal import Decimal
import numpy as np
import pytest
from engines.checks import CheckEngine, CheckRunner, CheckSample, normalize


@pytest.mark.parametrize("source,target,text", [("es", "en", "Hola API"), ("en", "ar", "Hello API")])
def test_checks_compute_scores_delay_cost_and_recommend_cheapest_close_engine(source, target, text):
    sample = CheckSample(np.ones(16000, np.float32), 16000, source, target, text)
    def engine(name, cost):
        return CheckEngine(name, lambda s: dict(source_text=text, translated_text="Translated", delays=[1,2], cost_usd=cost), Decimal(".2"))
    runner = CheckRunner()
    candidates = [engine("expensive", ".002"), engine("cheap", ".001")]
    results = runner.run([sample], candidates)
    assert all(r["wer"] == 0 and r["words_right"] == 100 and r["english_term_recall"] == 1 for r in results)
    assert results[0]["delay_p50_s"] == 1.5 and results[0]["delay_p95_s"] == pytest.approx(1.95)
    assert runner.recommend(results) == "cheap"
    assert runner.estimate([sample], candidates) > 0


def test_recording_without_reference_never_invents_accuracy():
    sample = CheckSample(np.zeros(16000), 16000, "es", "en")
    result = CheckRunner().run([sample], [CheckEngine("fake", lambda s: {"source_text":"hello", "delays":[1]})])[0]
    assert result["wer"] is None and result["words_right"] is None
    assert CheckRunner.recommend([result]) is None
    assert normalize("أ إ آ ة ١٢٣") == "ا ا ا ه 123"


def test_saved_checks_are_scoped_to_pair_engine_and_machine(tmp_path):
    from engines.checks import CheckStore
    path = tmp_path / "checks.json"
    store = CheckStore(path, machine="fixture-machine")
    store.save("es", "en", [{"engine":"fake", "wer":0, "outputs":[{"source":"PRIVATE"}]}])
    assert store.results("es", "en")[0]["engine"] == "fake"
    assert not store.results("en", "ar")
    assert not CheckStore(path, machine="other-machine").results("es", "en")
    assert "PRIVATE" not in path.read_text()
