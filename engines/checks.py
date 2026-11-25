"""Comparable in-app checks, with cached local inference and injected providers."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import time
import unicodedata
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np

from engines.delay import percentile


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold().translate(str.maketrans("أإآٱىة٠١٢٣٤٥٦٧٨٩", "اااايه0123456789"))
    return " ".join("".join(c if c.isalnum() or c.isspace() else " " for c in text if unicodedata.category(c) != "Mn").split())


def word_errors(reference, hypothesis):
    a, b = normalize(reference).split(), normalize(hypothesis).split()
    row = list(range(len(b)+1))
    for i, word in enumerate(a, 1):
        following = [i]
        for j, candidate in enumerate(b, 1):
            following.append(min(following[-1]+1, row[j]+1, row[j-1]+(word != candidate)))
        row = following
    return row[-1], len(a)


@dataclass
class CheckSample:
    audio: np.ndarray
    sample_rate: int
    source: str
    target: str
    reference: str | None = None
    variety: str = ""
    label: str = "Recording"

    @property
    def seconds(self):
        return len(self.audio) / self.sample_rate


@dataclass
class CheckEngine:
    name: str
    run: object
    hourly_estimate: Decimal = Decimal(0)


class CheckRunner:
    def estimate(self, samples, engines):
        hours = Decimal(str(sum(sample.seconds for sample in samples))) / 3600
        return sum((engine.hourly_estimate * hours for engine in engines), Decimal(0))

    def run(self, samples, engines):
        results = []
        for engine in engines:
            errors = words = kept = expected = 0
            delays, outputs, costs = [], [], Decimal(0)
            referenced = True
            for sample in samples:
                observation = engine.run(sample)
                text = observation.get("source_text", "")
                outputs.append({"source": text, "target": observation.get("translated_text", "")})
                delays.extend(v for v in observation.get("delays", []) if v is not None)
                costs += Decimal(str(observation.get("cost_usd", 0)))
                if sample.reference is None:
                    referenced = False
                else:
                    e, n = word_errors(sample.reference, text)
                    errors, words = errors + e, words + n
                    terms = Counter(re.findall(r"\b[a-z]+\b", sample.reference.casefold()))
                    seen = Counter(re.findall(r"\b[a-z]+\b", text.casefold()))
                    expected += sum(terms.values())
                    kept += sum((terms & seen).values())
            wer = errors / words if words and referenced else None
            seconds = sum(sample.seconds for sample in samples)
            results.append({"engine": engine.name, "wer": wer,
                "words_right": max(0, 100*(1-wer)) if wer is not None else None,
                "english_term_recall": kept/expected if expected and referenced else None,
                "delay_p50_s": percentile(delays, .5), "delay_p95_s": percentile(delays, .95),
                "cost_usd": str(costs), "cost_per_speech_hour": str(costs * 3600 / Decimal(str(seconds))) if seconds else "0",
                "outputs": outputs, "label": "measured"})
        return results

    @staticmethod
    def recommend(results):
        scored = [r for r in results if r["wer"] is not None]
        best = min((r["wer"] for r in scored), default=None)
        eligible = [r for r in scored if r["wer"] <= best + .03 and r["english_term_recall"] is not None
                    and r["english_term_recall"] >= .8 and r["delay_p95_s"] is not None and r["delay_p95_s"] <= 2.5]
        return min(eligible, key=lambda r: Decimal(r["cost_per_speech_hour"]))["engine"] if eligible else None


class SampleCatalog:
    """Downloads public audio/reference data only, never weights or credentials."""
    def __init__(self, *, fetch=None):
        self.fetch = fetch or self._fetch

    @staticmethod
    def _fetch(url):
        if not url.startswith("https://"):
            raise ValueError("Public samples require HTTPS")
        with urlopen(url, timeout=20) as response:
            data = response.read(8*1024*1024+1)
        if len(data) > 8*1024*1024:
            raise ValueError("Public sample exceeds the download limit")
        return data

    @staticmethod
    def recording(path, source, target, *, reference=None, variety=""):
        import soundfile as sf
        from audio_processing import resample_audio
        audio, rate = sf.read(path, dtype="float32", always_2d=True)
        audio = resample_audio(audio.mean(axis=1), rate, 16000)
        return CheckSample(audio, 16000, source, target, reference, variety)

    def public(self, source, target, *, variety="", full=False):
        manifest = json.loads((Path(__file__).parent / "data/check_samples.json").read_text(encoding="utf-8"))
        spec = next((s for s in manifest["special_sets"] if s["source"] == source and s["target"] == target), None)
        if spec:
            base = spec["base"]
            rows = [json.loads(line) for line in self.fetch(base + "/metadata.jsonl").decode().splitlines()]
            receipt = json.loads((Path(__file__).parent / "data/saudi_public_30.provenance.json").read_text())
            selected = {item["source_file"]: item for item in receipt["selection"]}
            rows = rows if full else [row for row in rows if row["audio_file"] in selected]
            samples = []
            for row in rows:
                data = self.fetch(base + "/audio/" + row["audio_file"])
                pin = selected.get(row["audio_file"])
                if pin and hashlib.sha256(data).hexdigest() != pin["source_sha256"]:
                    raise ValueError("Public sample integrity check failed")
                sample = self.recording(io.BytesIO(data), source, target, reference=row["transcript"], variety=variety)
                sample.label = spec["label"]
                samples.append(sample)
            return samples
        config = manifest["fleurs_configs"].get(source)
        if not config:
            raise ValueError("No public sample for this language. Use a recording.")
        url = "https://datasets-server.huggingface.co/rows?" + urlencode(dict(dataset="google/fleurs", config=config, split="test", offset=0, length=3))
        rows = json.loads(self.fetch(url))["rows"]
        samples = []
        for item in rows:
            row = item["row"]
            audio = row["audio"]
            url = audio[0]["src"] if isinstance(audio, list) else audio["src"]
            sample = self.recording(io.BytesIO(self.fetch(url)), source, target, reference=row["transcription"], variety=variety)
            sample.label = "Google FLEURS · CC BY 4.0"
            samples.append(sample)
        return samples


def local_engine(source, target, model):
    def run(sample):
        from tools.eval.runtime import DesktopRuntime, block_network
        saved = {key: os.environ.get(key) for key in ("OFFLINE_ONLY", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "WHISPER_MODEL")}
        try:
            with block_network():
                runtime = DesktopRuntime("offline", source=source, target=target, whisper_model=model)
                result = runtime.evaluate(sample.audio, sample.sample_rate)
            entries = result["entries"]
            return {"source_text": " ".join(e["source_text"] for e in entries),
                "translated_text": " ".join(e.get("translated_text", "") for e in entries),
                "delays": [e.get("delay_s") for e in entries], "cost_usd": 0}
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    return CheckEngine("local:" + model, run)


def cloud_engine(factory, settings, *, credentials, ledger, translator, lid):
    def run(sample):
        engine = factory.build(settings.provider(factory.name), credentials).engine
        engine.settings, engine.ledger, engine.translator, engine.lid = settings, ledger, translator, lid
        engine.variety = sample.variety
        events = []
        def spent():
            return sum(Decimal(v["estimated_usd"]) for v in ledger.snapshot()["providers"].values())
        before = spent()
        began = time.monotonic()
        engine.start((sample.source, sample.target), sample.target, False,
                     lambda kind, value: events.append((time.monotonic(), kind, value)))
        try:
            for at in range(0, len(sample.audio), 1600):
                if not engine.push_audio(sample.audio[at:at+1600]):
                    raise ValueError("The cloud check stopped at its cost gate")
                time.sleep(len(sample.audio[at:at+1600])/16000)
            engine.guard.close()
            time.sleep(2)
            source = [v["text"] for _, k, v in events if k == "input_transcription" and v.get("finished")]
            target = [v["text"] for _, k, v in events if k == "output_transcription" and v.get("finished")]
            if any(k == "fallback" for _, k, _ in events):
                raise ValueError("The cloud check failed; no score was recorded")
            completed = [at for at, k, v in events if k == "output_transcription" and v.get("finished")]
            return {"source_text": " ".join(source), "translated_text": " ".join(target),
                "delays": [max(0, at - began - sample.seconds) for at in completed[-1:]], "cost_usd": spent()-before}
        finally:
            engine.stop()
    rate = factory.rate
    hourly = rate.per_audio_hour if rate else Decimal(0)
    return CheckEngine(factory.name, run, hourly)
