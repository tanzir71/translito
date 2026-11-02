# Translation-quality implementation

Specification: `CODEX_HANDOFF_TRANSLATION_QUALITY.md` supplied by the owner.
Native macOS code is outside this change.

| Phase | Current evidence | Remaining work |
|---|---|---|
| P0 evaluation | Shared desktop replay, WER/CER/chrF and bilingual metrics, latency/RAM/cost reports, cache-only socket-blocked run; see P0_BASELINE.md | Cohere hardware measurements after runtime upgrade and gated access. Saudi meeting set waived by owner; those accuracy targets are unverified. |
| P1 local quality | Bilingual runtime/GUI, pair LID/pass-through, assembly, glossary/protection/Terms editor, migration, hallucination guards, VAD endpointing, retained speech/lag, four-beam MT, hardware-aware faster-whisper and verified Opus/pivots. Cohere/CT2 setup plus optional pinned TranslateGemma GGUF with consent, context, cancellation and Lite fallback. First-run 8-second CPU speed check. Replay now exercises the bilingual controller; public/synthetic audio completes with sockets blocked. 149 tests pass. | Real Cohere/Gemma speed/accuracy checks require owner model access/terms. Fallback latency misses 4s; Saudi accuracy is unverified. Free cloud routing and its latency checks remain P2/P3. |
| P2 provider infrastructure | Typed provider failures, ordered ASR/MT fallback, enabled/Test fingerprint gates, Credential Manager-only keys, Free/Offline/Custom profiles, stage-aware amber engine chip, additive migration, durable UTC-month usage/history and reserve-before-call caps. P3 adds provider cards, actual-usage settlement, restart-safe rolling quotas and Advanced one-way routing. | Live-account verification needs configured, tested provider keys. |
| P3 cloud providers | Registered Azure F0, DeepL Free, Google Basic, opt-in Gemini Flash-Lite, Cohere trial and Groq adapters. Shared pair LID/postprocessing; ready/fast local Cohere → Cohere API → Groq → local Whisper. Explicit Test/usage/privacy cards inspected in Windows preview. Gemini/Cohere trial reuse consent starts unchecked. Mock HTTP contracts, simulated-hour metering, setup failure gates, cross-process quotas and cancellation covered. Full suite: 224 passed. | No live key or cloud accuracy/latency result. The simulated Azure hour checks accounting only. Private Saudi set waived by owner; Azure-vs-local chrF acceptance remains unverified. Optional transcript refinement deferred. |
| P4 capped booster | Thin eval wire contracts for Soniox v5, Speechmatics Enhanced/Melia and ElevenLabs Realtime. Gemini Live preview worker with explicit free/Test/reuse gates, 100ms input, resumption/reconnect/Stop, usage reservations and fake installed-SDK wire check. Persistent PCM output, sample-rate alignment and rebound-device retention. No real inference or paid call. | Paid eval transport/accounting runner, approved accounts/spend, measured winner. Gemini desktop row/capture/voice-policy integration and live acceptance remain incomplete; the worker is not registered in the UI. |
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
CT2 → selected stock Whisper; P3 adds configured cloud fallbacks before Whisper.

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
P0 <https://github.com/tanzir71/translito/pull/6>; P2 stacked on P1
<https://github.com/tanzir71/translito/pull/7>; P3 stacked on P2
<https://github.com/tanzir71/translito/pull/8>. These remain drafts. No quality
installer or production-site update has been published yet.

P2 core is developed on `codex/p2-provider-routing`, stacked on P1. The bilingual
controller now calls ASR/MT routers even for local-only sessions. Offline replay
explicitly selects the private profile, so `--allow-downloads` cannot opt into
cloud inference. P3 now registers the free-provider contracts. Disabled or untested
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

P3 shares one pair-LID pass and the same language/script checks across local and
cloud recognizers. A slow or failed local Cohere model yields to tested Cohere
trial, then Groq, before the local Whisper fallback. Audio is VAD-gated mono WAV;
local token buckets and durable rolling quotas bound requests. Groq's 10-second
billing minimum is retained separately from actual audio duration. Advanced
one-way mode also calls the provider routers. A tested cloud MT provider can
handle a pair without a published Marian model; unavailable fallback translation
keeps the recognized source visible with an error.

Provider Test invalidates the old key fingerprint before changing credentials,
uses a fixed public text or bundled public Arabic clip, and leaves failures
disabled. Key, region, tier and reuse-consent changes require another Test.
Cohere's trial terms allow research reuse and say trial use is not intended for
personal information, so that card has a separate unchecked consent gate, like
Gemini Free. DeepL uses the Free endpoint and rejects non-Free keys. Its immutable
app-owned glossary IDs are cached without raw keys or terms. Existing remote and
local glossary versions are retained.

Successful metering can reduce a conservative reservation while preserving its
original units and settlement history. Simulating 240 Azure utterances (one hour
at 15 seconds each) recorded 44,160 characters, 240 requests and $0. This used
MockTransport, not Azure; no claim about live MT quality or real-account billing
follows from it. Free cloud evaluation requires a separate `--allow-cloud`
upload opt-in and enabled/tested providers. `--allow-downloads` alone keeps all
cloud inference disabled. Monthly and rolling quotas also survive process and
calendar changes in the tests.

All six provider cards were inspected in the Windows preview; key entries are
masked, cloud enables/reuse choices start unchecked and the paid cap stays $0.
The preview Test action performs no key access, requests or settings writes.
The full test suite passed 224 tests. Real config remains 427 bytes with its
original 2026-10-28 timestamp; no real usage.json was created. Cloud quality and
latency acceptance requires a live configured account and remains unverified.
