# Evaluation inputs

Install `requirements-dev.txt`. No recording or upload happens automatically.

Place these files together for each clip:

```
meeting-01.wav
meeting-01.ref.src.txt      # transcript, one utterance per line
meeting-01.ref.tgt.txt      # reference translation into --target
meeting-01.ref.tag.txt      # en, ar or mix, one per source line (optional)
meeting-01.ref.terms.json   # {"replica": ["ربليكا", "ريبليكا"]} (optional)
```

Use 15–30 short Saudi meeting clips (Najdi/Hijazi/Gulf), at least one third
code-switched. Include pure Arabic, Arabic-accented English, embedded English
technical terms and alternating languages. Keep private WAVs/references outside
the repo, or in the ignored `private/` folder. Do not commit private predictions.
The owner has currently waived supplying these clips; Saudi acceptance metrics
remain unverified until a representative set is available.

Alternatively, ignored `tools/eval/sets.local.json` holds paths relative to itself:

```json
{"clips": ["D:/PrivateMeetingEval/meeting-01.wav"]}
```

Run from the repository root:

```powershell
python tools/eval/run_eval.py --input D:/PrivateMeetingEval --profiles baseline,offline
python tools/eval/run_eval.py --manifest tools/eval/sets.local.json --bench
```

By default model loading is cache-only and sockets/DNS are blocked for the whole
worker process, including initialization. `--allow-downloads` allows local model
downloads, not cloud ASR/MT uploads. Cloud profiles will require enabled, tested
provider credentials when P2/P3 land. Unsupported profiles fail explicitly.

Every profile and benchmark model runs in a fresh process. Output goes to a new
UTC-stamped directory under `tools/eval/results/`, never overwriting a prior run:

- `metrics.csv`: per-clip WER, CER, chrF, tag accuracy, English-term recall,
  annotated transliteration rate and coverage, unnecessary-MT rate, repetition
  count, segment latency p50/p95, real-time factor, usage and cost estimate.
- `summary.md`: comparison table and aggregate bilingual counts.
- `run.json` and worker JSON: exact predictions, versions, commit, timings and
  errors. Treat these as sensitive if the input is private.

WER/CER normalize punctuation, whitespace, NFC and case only. Arabic diacritics
and English spellings are preserved. Latin words are counted with multiplicity.
Transliteration cannot be reliably inferred without spellings: absent annotations
produce **n/a**, not a misleading zero. Tag scoring aligns utterances by order;
missing/extra output rows count as wrong, so segmentation differences affect it.
Use one utterance per clip for isolated recognizer comparisons.

Latency excludes model load. Faster-than-real-time replay advances capture time
from WAV offsets and adds measured inference time to the consumer clock. It
keeps all segments, services the real sentence assembler's idle deadline and
includes simulated backlog plus endpoint silence in speech-end latency. EOF
flushes the last pending sentence, as ending capture normally would. This is a
single-consumer simulation; it does not measure live capture/device contention.
The Offline profile uses the actual bilingual controller. MT counts come from
that controller's translator, including assembled rows and English pass-through.
Glossary defaults are read/merged in memory, without changing user files.
Benchmark `--bench`
reports RTF and sampled peak process-tree RSS for Cohere fp32/bf16/int8, turbo
int8 and base language-ID. Missing runtime/gated weights are **unavailable**,
never assumed to pass. Dynamic quantization is experimental and must be measured.

The archived P0 baseline records commit `d1e4092` through the P0 extraction.
The current `baseline` option selects legacy windows and one-way routing in the
current runtime; it is not a frozen copy of old model adapters/generation code.
Use the P0 checkout when reproducing the historical baseline exactly.
Public MSA or synthetic clips can smoke-test the harness, but cannot establish
Saudi dialect accuracy, code-switching recall or provider superiority.
