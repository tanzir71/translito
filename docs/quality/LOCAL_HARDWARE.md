# Local hardware probes

The P0 hardware runner uses the desktop recognizer adapters and VAD segmenter.
Protocol `desktop-vad-and-local-adapter-v2` replaces the original independent
Cohere decoder and unguarded Turbo call. Historical P0 numbers remain in
`P0_BASELINE.md`; different segmentation/decoding protocols must not be treated
as a controlled speed comparison.

## Cache-only measurement

```powershell
python -B tools/eval/run_eval.py --manifest D:\PrivateEval\sets.local.json `
  --bench --recognizers cohere-fp32,cohere-bf16,cohere-int8,turbo-int8,small-int8,base-lid `
  --source ar --output D:\PrivateEval\hardware-results
```

The manifest needs a `clips` list of WAV paths; hardware-only runs do not need
reference sidecars. Use `--source en` with English clips for the English decoder
comparison. The runner never opens capture devices, starts TTS, saves desktop
transcripts, changes app settings or enables a cloud inference provider.
Without `--allow-downloads`, sockets/DNS are blocked even for direct calls to
`benchmark()`, and model loaders use local files only. The surrounding offline
environment is restored after the probe.

Each candidate runs in a separate process. Cohere uses
`CohereLocalRecognizer`, including the model folder selected in the app, the
chosen fp32/bf16/dynamic-Linear-int8 precision, VAD rejection, language tag,
duration-scaled output limit, decoder chunk metadata and shared postprocessing.
Its detector/model loading is outside decoder timing. CPU threads use the
app's physical-cores-minus-one policy.

Whisper Small/Turbo use `FastWhisperASR`, CPU int8 and Balanced beam size 3,
including the shared hallucination/repetition guards. They honor the app's
configured local Whisper override before the normal HF cache, with explicit
`token=False` for HF cache/download resolution. `base-lid` uses the app's
pair-restricted detector; it is not a speech-to-text measurement.

`codeswitch-int8` is an optional probe for the app's prepared Arabic/English
CT2 fallback. Its app loader validates the matching tokenizer. It is tuned on
Egyptian speech; a result does not establish Saudi recognition quality.

## Explicit downloads and gated access

Cached Cohere never reads Credential Manager. Generic `--allow-downloads`
does not authorize a gated Cohere download: that candidate still tries only
the configured cache. To download its weights, the owner must first accept
the conditions on Hugging Face, save a read token through the app's masked
Cohere setup, and explicitly supply **both** `--allow-downloads` and
`--cohere-terms-accepted`. The latter is an attestation that acceptance already
happened; it does not accept conditions on the owner's behalf. The key comes
only from Windows Credential Manager and is never copied into arguments,
environment variables or reports. Missing keys fail before model construction.

Public Whisper/fallback model downloads need `--allow-downloads`, use verified
Windows TLS, and never upload evaluation audio. Once cached, rerun with both
network-enabling flags omitted.

## Interpreting the report

- `rtf`: decoder seconds / original input seconds.
- `segment_rtf`: decoder seconds / VAD-positive segment seconds. The 0.7
  component headroom gate uses this value so long silence cannot hide a slow
  decoder. Segment audio includes the app's pre-roll/trailing-silence policy.
- Model/VAD load times and segmentation compute are recorded separately.
  ASR probes force `--source`; conversation LID and MT are excluded. These
  measurements do not prove the four-second Free end-to-end latency target.
- `no_speech` skips recognizer loading and has no passing speed result.
  Empty transcriptions, LID-only probes, unavailable models and failed/partial
  runs cannot set `asr_speed_gate_passed`. Even a true value proves only this
  component speed check; it is not quality acceptance or an automatic model
  recommendation.
- Reports retain input hashes, adapter/model/precision/thread metadata,
  segment predictions, empty-output counts and relevant library versions.
  Earlier predictions survive a later segment error, while primary speed
  fields remain unavailable. SDK error text/keys are not echoed.

Timestamped output directories preserve earlier reports. The owner waived
private Saudi clips, so public MSA and synthetic probes remain smoke evidence.
Gated Cohere weights, real free-cloud comparisons and Saudi accuracy/latency
acceptance remain unverified until their required access/evidence is available.

## Public smoke measurements — 2026-11-02

Source revision: `5c52768c56fb3844de1f1ac8247b64fe43dc9952`, no tracked
changes during the run. Input: Google FLEURS `ar_eg` test row 0, 8.16 seconds,
CC BY 4.0, [dataset source](https://huggingface.co/datasets/google/fleurs).
SHA-256: `40d979a6239fc08951f387c671fb5fc46fffdc5df823ed1dbdb809bc75e26620`.
VAD emitted one 7.852-second segment. AMD Family 25 Model 80 CPU, six physical
cores; the CTranslate2 probes used five threads, CPU int8 and beam size 3.
Runtime: Torch 2.13.0+cpu, Transformers 5.22.1, faster-whisper 1.2.1,
CTranslate2 4.8.4, Silero 6.2.3. Sockets/DNS were blocked, no download or
gated-access flag was supplied, and no paid call was made.

| Probe | Status | Decode (s) | Decode/segment RTF | Peak RSS (GiB) | Model load (s) |
|---|---|---:|---:|---:|---:|
| Cohere fp32 | Cache/access required | n/a | n/a | n/a | n/a |
| Cohere bf16 | Cache/access required | n/a | n/a | n/a | n/a |
| Cohere dynamic int8 | Cache/access required | n/a | n/a | n/a | n/a |
| Turbo int8 | Measured | 8.429 | 1.074 | 1.968 | 4.159 |
| Small int8 | Measured | 2.727 | 0.347 | 0.636 | 0.495 |
| Base pair LID | Measured, LID only | 0.548 | 0.070 | 0.444 | 0.861 |

Small passed this component's speed gate with a nonempty transcription; Turbo
missed it. Neither result establishes Saudi quality or full Free-profile latency.
Unavailable Cohere process startup RSS is not reported as model memory.
Artifacts are retained locally under
`D:\CodexBuilds\Translito-quality\hardware-v2-results\20261102T170020.948528Z`.

A separate cache-only desktop Offline replay, at the same source revision,
produced one source/target row with no pipeline errors. It used local Small
and Marian fallback, with the existing Balanced preset. Observed WER 0.533,
CER 0.131, chrF 46.42 and speech-end-to-completed-row time 6.888 seconds.
The four-second target is **not met** on this fallback sample. One utterance
does not establish a latency distribution or language-ID accuracy, and there
were no reference English terms for code-switching scores. These are smoke
results, not a controlled comparison with the historical P0 protocol.
Replay artifacts remain under
`D:\CodexBuilds\Translito-quality\quality-v2-replay\20261102T170258.712716Z`.

A diagnostic MT thread probe confirmed Silero's import changed Torch threads
from six to one. On the same warmed public source text, two MT calls per setting
produced identical output: one thread took 1.462/1.353s, three threads
1.149/1.155s, five threads 1.232/1.147s. VAD compute was 0.284s, 0.261s
and 0.293s respectively. This small test does not close the observed pipeline
gap or justify a production-wide thread change. Its data is retained in
`D:\CodexBuilds\Translito-quality\mt-thread-probe-20261102T170934.539211Z.json`.
The probe helper now applies its explicit Cohere thread setting after VAD
initialization and reports the actual Torch count, including direct calls.

## Bilingual switching smoke — 2026-11-02

At source revision `7b58358d435fad32aac9cc4bdca45003f57f438e`, a cache-only
Offline replay combined two locally synthesized Microsoft Hazel English
utterances with the same public Arabic clip, separated by 1.4-second silences.
This is a 19.447-second synthetic/public MSA fixture, not a Saudi meeting or a
natural mixed-language utterance. The selected source was Arabic and target
English, using the existing Balanced preset; sockets/DNS were blocked.

The desktop controller produced three rows tagged EN → AR → EN. Both English
rows passed through unchanged apart from punctuation, with zero English WER,
no MT calls and all 18 English reference terms retained. The Arabic row made
the only MT call (94 characters). There were no pipeline errors or repetition
loops. Arabic WER remained 0.533 and overall target chrF was 70.69; the English
rows must not be used to claim improved Arabic quality.

Observed speech-end-to-completed-row times were 3.698, 10.838 and 5.138 seconds
(three-row p95 10.268 seconds). The four-second latency target remains unmet.
This replay verifies the functional language switching/pass-through path only;
three rows do not establish the required language-ID accuracy distribution.
The later code-switch preset fix does not affect this run, whose prepared
code-switch weights were unavailable.

Fixture metadata, source hashes and exact timeline are retained at
`D:\CodexBuilds\Translito-quality\bilingual-smoke-20261102T172903.5519989Z\composite.json`.
Reports and raw row predictions are retained at
`D:\CodexBuilds\Translito-quality\bilingual-smoke-results\20261102T173129.669922Z`.
