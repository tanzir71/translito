# Evaluation-only streaming runner

`tools/eval/run_eval.py` accepts `soniox`, `speechmatics`,
`speechmatics-melia` and `elevenlabs` alongside the P0 local/free profiles.
These candidates are **not registered in the desktop app**. No paid evaluation
has been run and no winner has been selected. The owner waived private Saudi
clips; public MSA or synthetic evidence cannot establish Saudi meeting accuracy.

## Authorization and accounting

The default paid allocation is zero. Paid profiles require both `--allow-cloud`
and `--allow-paid`, plus a separate owner-approved policy. `--allow-downloads`
does not authorize these profiles. An Offline process rejects them.

Copy `tools/eval/paid-policy.example.json` into a private location. The example
deliberately cannot run: its caps are zero and every ceiling is unverified.
Before changing those fields, obtain the owner's spending approval and verify
the selected account's model, enabled features, billing granularity, minimum
charges, remaining credits and enforceable account/project limit. Do not assume
signup credit, training discounts or an advertised hourly estimate is a ceiling.
If the account cannot establish a maximum session charge, leave
`ceiling_verified` false and do not run that candidate.

`session_ceiling_usd` is the verified maximum charge for **one complete session
of at most 120 seconds**, including handshake/wait/drain and enabled features.
It is an explicit account policy, not a rate discovered or guaranteed by this
tool. This is particularly important for Soniox's audio **and text token**
billing. The runner cannot independently enforce an upstream account limit.
It therefore does not qualify as a production hard-cap implementation.

Keys are read only from Windows Credential Manager, using provider names
`soniox`, `speechmatics` and `elevenlabs` in the existing `Translito` service.
Save them with `CredentialStore.save()` using an interactive hidden prompt;
never put a key in CLI arguments, environment variables or policy files.
`credential_sha256` is SHA-256 of the stripped key and binds the verified
account policy to that exact credential. Changed credentials fail before
reserving usage or opening a connection.

The full session ceiling is reserved in **both** ledgers before connecting:

- `--paid-usage` is the persistent evaluation-only UTC-month ledger (default
  `<output>/paid-usage.json`), shared by all candidates and retained across runs.
- The timestamped run directory contains `paid-run-usage.json`, shared by its
  child processes. Its whole-history cap prevents a UTC-month boundary from
  resetting the approved run allocation.

The complete allocation stays charged to these ledgers on success, failure,
timeout, quota rejection, cancellation or crash. Protocol completion is not
proof of the actual invoice. Reports distinguish this retained allocation from
an observed bill; they record actual PCM duration separately from the ledger's
120-second reservation. No automatic refunds, reconnects or audio resends occur.
Do not rotate/delete ledgers to bypass a cap. An uncalled run reservation is
released if the monthly ledger refuses it before any connection.

## Running an approved comparison

Use the existing WAV + `.ref.src.txt` / `.ref.tgt.txt` sidecars. All paid clips
must be at most 90 seconds, leaving room for startup and final draining.
Keep the persistent monthly ledger at the same path across comparisons.

```powershell
python -B tools/eval/run_eval.py --manifest D:\PrivateEval\sets.local.json `
  --profiles offline,speechmatics,elevenlabs --allow-cloud --allow-paid `
  --paid-policy D:\PrivateEval\approved-policy.json `
  --paid-usage D:\PrivateEval\paid-usage.json --output D:\PrivateEval\results
```

This command is documentation, not spending approval. The owner has not approved
paid calls in the current session, so it has **not been executed**.

The default MT stage is the cached local desktop translator. Its warmup runs
before connecting and requires cached models. To compare the handoff's free
cloud MT chain, add `--stream-mt free_cloud` after enabling and Testing the
desired free MT provider in the app. This reuses the desktop free-tier quota
ledger and fallback checks with a zero paid text cap. It does not enable cloud
ASR, write settings or capture live audio.

Transport sends 16kHz mono PCM16 in 100ms frames while receiving concurrently.
Its operation timeout is 110 seconds, leaving ten seconds of the 120-second
allocation for cancellation and socket cleanup.
It uses verified Windows TLS, header credentials, bounded startup/session/drain
timeouts and no proxies, redirects, payload debug logs or automatic retries.
Speechmatics waits for RecognitionStarted and counts only audio frames in EOF.
Melia's ForceEndOfUtterance events come from the same local VAD segmenter as P0.
Speechmatics/ElevenLabs finalized text enters the desktop sentence assembler,
glossary protection, bilingual pass-through and MT controller.

## Measurement limits

All P0 report artifacts are retained: references, predictions, WER/CER/chrF,
English-term recall, annotated transliteration, MT calls, RAM and allocation.
Partial hypotheses are excluded from final transcript scoring.

Soniox uses one-way target-language captions for this bake-off. Final source
and target token streams are clip-scored; already-target-language `none` tokens
pass through. Native translated tokens have no audio timestamps or 1:1 source
alignment, so per-utterance tag and latency scores are **unavailable**. This
runner does not establish the handoff's two-way desktop/voice acceptance.

Speechmatics latency uses vendor final-word timestamps and desktop MT completion;
it is labeled accordingly, rather than claiming independently measured acoustic
speech-end timing. ElevenLabs delayed timestamp events do not duplicate rows or
MT calls. Their timestamps are not currently joined back to earlier commits,
so latency remains unavailable. ElevenLabs has no EndOfTranscript marker: EOF
requires a post-EOF commit followed by a bounded quiet drain. Missing confirmation,
provider failures and MT failures make the run fail its acceptance gate.

Synthetic socket tests verify transport and accounting behavior. They do not
measure vendor recognition quality, speed, account billing or meeting suitability.
Keep Free recommended until an approved, representative comparison demonstrates
the handoff's gain and latency criteria.
