# Translation-quality implementation

Specification: `CODEX_HANDOFF_TRANSLATION_QUALITY.md` supplied by the owner.
Native macOS code is outside this change.

| Phase | Current evidence | Remaining work |
|---|---|---|
| P0 evaluation | Shared desktop replay, WER/CER/chrF and bilingual metrics, latency/RAM/cost reports, cache-only socket-blocked run; see P0_BASELINE.md | Cohere hardware measurements after runtime upgrade and gated access. Saudi meeting set waived by owner; those accuracy targets are unverified. |
| P1 local quality | Bilingual runtime/GUI, pair LID/pass-through, assembly, glossary/protection/Terms editor, migration, hallucination guards, VAD endpointing, retained speech/lag, four-beam MT, hardware-aware faster-whisper and verified Opus/pivots. Cohere/CT2 setup plus optional pinned TranslateGemma GGUF with consent, context, cancellation and Lite fallback. First-run 8-second CPU speed check. Replay now exercises the bilingual controller; public/synthetic audio completes with sockets blocked. 149 tests pass. | Real Cohere/Gemma speed/accuracy checks require owner model access/terms. Fallback latency misses 4s; Saudi accuracy is unverified. Free cloud routing and its latency checks remain P2/P3. |
| P2 provider infrastructure | Typed provider failures, ordered ASR/MT fallback, enabled/Test fingerprint gates, explicit pricing-policy gate, Credential Manager-only keys, Free/Offline/Custom profile selection, stage-aware amber engine chip, additive migration, durable UTC-month usage/history and reserve-before-call dollar caps. Pending reservations survive restarts; threads and separate processes share the cap. 175 tests pass. Profile section inspected in Windows preview. | Register cloud adapters and provider Test/usage cards alongside P3. One-way Advanced still uses its legacy local path; route it before exposing cloud there. |
| P3 cloud providers | Not implemented yet | Verified adapters, request tests, configured-provider end-to-end checks and optional transcript refinement. |
| P4 capped booster | No provider selected, enabled or charged | Thin evaluation adapters, owner-approved paid bake-off, measured winner, streaming/reconnect/budget tests. Gemini preview remains opt-in. |
| P5 virtual mic/capture | Not implemented yet | Pinned attributed bundle, consent/elevation flow, self-test, guided setup and process loopback. Browser extension is optional and currently deferred. |
| P6 release | No quality release built or published | Docs/privacy, version bump, rebuilt installer, installed verification and download-site update after the implementation gates. |

Decisions pending from the owner: recommended bilingual defaults; VB-CABLE
redistribution; optional browser extension; approved test spend/monthly booster
cap and configured provider accounts. Until explicit spending approval, the
paid cap is $0 and no paid provider is contacted. Missing data, credentials or
model access are not replaced with fabricated acceptance results.

Each phase is developed as its own PR. Existing transcripts and user settings
are preserved. No production engine, capture behavior, model default or paid
setting has changed in P0.

P1 test changes are intentional: the old fixed-window tests explicitly select
`legacy_fixed_window=True`; new endpointing tests cover the production default.
The old drop-oldest queue test now requires all waiting speech to be retained.
No user config migration or glossary write has been run against real settings;
all migration/merge tests use temporary directories.

P1 runtime compatibility was checked in a separate environment using
Transformers 5.22.1 / huggingface-hub 2.4.0; the installed release and old build
environment remain intact. Marian translation no longer depends on the removed
`translation` pipeline. Cohere's actual feature extractor was exercised with
network calls blocked, including its required librosa backend. Gated model
weights were not downloaded and no cloud inference was enabled.

The public smoke clip at P1 commit `e0cca3d` produced one row, WER 0.467,
CER 0.101, chrF 56.86 and speech-end latency 5.082s. This improves segmentation
and translation on that clip, but does not establish Saudi accuracy or the
4-second latency target. Later runtime upgrades reproduced the recognized and
translated text. Existing transcript files are now protected by exclusive
creation with unique suffixes, including repeated Save/Stop/exit saves.

The live bilingual controller is covered by source-before-target, EN no-MT,
sentence/language boundary, voice/mute/pass-through, timeout, cancellation and
error-retention tests. Windows preview showed that Tk renders isolate controls
as boxes; bidi ordering alone also reversed Arabic letters. The verified fix
shapes Arabic before explicit bidi ordering, leaves stored strings untouched,
and right-aligns Arabic-matrix rows. See `tests/fixtures/bidi/` for the captured
reference and verification limits. The installed app has not been replaced by
this development branch yet.

The code-switch CT2 repository exists but does not ship tokenizer.json. The
source model's tokenizer was checked against its vocabulary: all 51,865 IDs
match. Managed downloads obtain only inference files and that tokenizer; an
offline loader refuses an incomplete/mismatched cache instead of fetching a
tokenizer implicitly. Cached fallback order is Cohere Arabic → code-switch
CT2 → selected stock Whisper; cloud fallback is still pending P2/P3.

Empty recognition now restores Listening with a rate-limited hint. Speak capture
is retained while buffered speech plays. The sentence timeout uses capture
speech activity/end time, avoiding an extra 1.5s delay after slow ASR. More
complete streaming/player verification remains required before the final Speak
end-to-end test. Stop/restart now isolates session queues/cancellation: a slow
old TTS worker cannot consume or play the next session's utterances. Regression
tests cover that race and output-route retry cancellation.

TranslateGemma uses a pinned Q4_K_M GGUF, checksum and embedded-template check,
CPU-only llama.cpp wheel, structured language codes, 2,048-token context,
physical-core threads and a 3x original-input output cap. It retries lost terms
once, then visibly falls back to Marian. Preferred glossary translations and
per-call cancellation work in both local MT paths. Weights are not bundled or
downloaded by this implementation run; the unchecked consent step is in Settings.
The Gemma setup dialog was inspected in the Windows preview.

The bundled speed check is an attributed, trimmed CC BY 4.0 FLEURS sample. An
actual socket-blocked run decoded 8.00s in 9.574s (RTF 1.197, CPU int8, 5 threads)
and recommended Small. Timing is sample-specific and excludes model load.

Current bilingual replay uses the WAV capture clock and measured inference time
to retain backlog/assembler deadlines. It does not flush after every chunk.
Read-only glossary loading avoids user-data writes. Public MSA smoke produced
WER 0.533, CER 0.131, chrF 46.42 and 7.503s speech-end latency with stock
Whisper/Marian fallback. This fails the latency target and does not establish
Saudi quality. A synthetic Windows-SAPI English passage followed by the public
Arabic clip produced three rows, only one MT call, English-term recall 1.0,
unnecessary-MT rate 0, no pipeline errors and 6.675s speech-end p95. Its reference
has two utterance lines while ASR split English into two rows; tag alignment and
overall text scores are smoke evidence only. Local reports are in the quality
build's eval-results directories 20261102T111144.292623Z and 20261102T111658.078609Z.

Development PRs: P0 <https://github.com/tanzir71/translito/pull/5>; P1 stacked on
P0 <https://github.com/tanzir71/translito/pull/6>. Both remain drafts. No quality
installer or production-site update has been published yet.

P2 core is developed on `codex/p2-provider-routing`, stacked on P1. The bilingual
controller now calls ASR/MT routers even for local-only sessions. Offline replay
explicitly selects the private profile, so `--allow-downloads` cannot opt into
cloud inference. No cloud factories are registered yet. Disabled or untested
providers are never instantiated; a changed key, region, tier or training choice
invalidates the Test fingerprint. Raw keys and meeting text are absent from
usage/config/router-error records.

Usage is stored in `usage.json` with retained monthly totals, reservation records
and append-only events. Reservations count while pending after a crash; uncertain
network failures conservatively retain their estimated charge. Confirmed auth or
quota rejection releases the reservation without deleting history. Free requests
still work after a paid cap is lowered to zero. The meter covers this app's
requests, not other software sharing the same provider key. No ledger write has
been made to the real user profile during these tests.
