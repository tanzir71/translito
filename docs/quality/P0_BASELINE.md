# P0 baseline: 2026-11-02

Baseline behavior is main commit `d1e4092c77c2e7fc91189fd1e5086505df97a3d7`.
P0 changes only extract capture-processor construction; ASR, fixed-window
segmentation, one-way routing and greedy MT remain unchanged.

The owner has no Saudi meeting evaluation set and asked to skip supplying it.
The following is a **public smoke baseline**, not Saudi accuracy acceptance.
No private transcript or meeting audio was uploaded. No paid call was made.

Input: Google FLEURS `ar_eg`, test row 0, 8.16 seconds, CC BY 4.0.
Source: <https://huggingface.co/datasets/google/fleurs>.
The source reference is the dataset transcript; the English reference is a
manual translation. Input WAVs and predictions remain local.

```
python tools/eval/run_eval.py --input <public-smoke-folder> --profiles baseline,offline
python tools/eval/run_eval.py --input <public-smoke-folder> --bench
```

Both commands used cache-only model loading with Python sockets/DNS blocked.
The two profiles are intentionally the same local pipeline in P0. Separate
processes yielded identical recognized/translated text but different timings;
a single short clip is insufficient for a stable latency distribution.

| Profile | WER | CER | chrF | Processing p50 / p95 | Entries | Errors | API cost |
|---|---:|---:|---:|---|---:|---:|---:|
| baseline | 0.467 | 0.192 | 37.47 | 6.321 / 7.690 s | 2 | 0 | $0 |
| offline | 0.467 | 0.192 | 37.47 | 8.594 / 10.983 s | 2 | 0 | $0 |

The single utterance was split into two rows. Their language-tag alignment
score is 0.5 because the extra row counts as wrong; this does not establish
language-ID accuracy. No Latin reference words occur, so term recall and
transliteration are n/a. End-of-speech latency is n/a for the old segmenter.
Peak process-tree RSS was about 1.06 GiB for both runs.

| Recognizer | Result | RTF | Peak RSS |
|---|---|---:|---:|
| Cohere Arabic fp32 | unavailable: installed Transformers lacks Cohere ASR | n/a | n/a |
| Cohere Arabic bf16 | same | n/a | n/a |
| Cohere Arabic dynamic int8 | same | n/a | n/a |
| faster-whisper turbo int8 | measured, CPU | 4.239 | 1.78 GiB |
| faster-whisper base LID only | measured, CPU | 0.189 | 0.26 GiB |

The bench used five CPU threads (`physical cores - 1`). Turbo misses the live
headroom target on this sample. Cohere performance remains unknown: its gated
weights and Transformers 5.4+ runtime must be made available before comparing.
At this P0 baseline commit, the release pinned Transformers 4.57.6; upgrading
also required testing the Marian MT path rather than assuming compatibility.
Windows 1.1.0 subsequently upgraded to Transformers 5.22.1. The corrected
shared-adapter/cache-aware probe protocol is described in `LOCAL_HARDWARE.md`;
it does not retroactively change these historical measurements.

Validation: all 36 tests passed, including actual desktop event replay with
fake models, WAV decoding, missing-reference validation, bilingual metric
counts, per-request usage minimums and offline socket blocking.

An initial replay failed because Windows redirected stdout could not print
Arabic. Its artifacts were retained, and it is **not** the baseline above.
The runner now uses UTF-8 and returns a failure exit code when pipeline errors
occur, after retaining diagnostic artifacts.
