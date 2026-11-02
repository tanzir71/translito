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
