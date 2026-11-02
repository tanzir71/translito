# Translation-quality implementation

Specification: `CODEX_HANDOFF_TRANSLATION_QUALITY.md` supplied by the owner.
Native macOS code is outside this change.

| Phase | Current evidence | Remaining work |
|---|---|---|
| P0 evaluation | Shared desktop replay, WER/CER/chrF and bilingual metrics, latency/RAM/cost reports, cache-only socket-blocked run; see P0_BASELINE.md | Cohere hardware measurements after runtime upgrade and gated access. Saudi meeting set waived by owner; those accuracy targets are unverified. |
| P1 local quality | Bilingual runtime/GUI, pair LID and pass-through, sentence assembly, glossary/protection/Terms editor, byte-preserving migration, hallucination guards, VAD endpointing, unbounded speech queue/lag, four-beam MT, hardware-aware faster-whisper, verified Opus pairs/pivots and Transformers 5 adapter. Cohere consent/key/download UI and managed code-switch fallback with a matching offline tokenizer. Actual Windows bidi, Terms and model-setup previews inspected. 135 tests pass. | TranslateGemma, first-run benchmark and remaining end-to-end/latency checks. Update evaluation replay for assembled bilingual rows. Exercise real bilingual audio through the new routing path. Cohere weights still need authorization before speed/accuracy measurement. |
| P2 provider infrastructure | Engine contracts, pure usage-cost calculation and Credential Manager-only key store | Provider fallback, durable history/caps, settings/test flows and engine chip. |
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
complete streaming/player lifecycle verification remains required: inspect
Stop/restart queue handling before the final Speak end-to-end test.

Development PRs: P0 <https://github.com/tanzir71/translito/pull/5>; P1 stacked on
P0 <https://github.com/tanzir71/translito/pull/6>. Both remain drafts. No quality
installer or production-site update has been published yet.
