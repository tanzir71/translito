# Translation-quality implementation

Specification: `CODEX_HANDOFF_TRANSLATION_QUALITY.md` supplied by the owner.
Native macOS code is outside this change.

| Phase | Current evidence | Remaining work |
|---|---|---|
| P0 evaluation | Shared desktop replay, WER/CER/chrF and bilingual metrics, latency/RAM/cost reports, cache-only socket-blocked run; see P0_BASELINE.md | Cohere hardware measurements after runtime upgrade and gated access. Saudi meeting set waived by owner; those accuracy targets are unverified. |
| P1 local quality | Tested routing/LID policy, 186-term additive glossary, span protection, byte-preserving config migration, shared hallucination guards, VAD endpointing, sentence assembler, unbounded speech queue with lag events, four-beam MT, turbo alias resolution and CPU/CUDA faster-whisper selection. Verified Opus pair/pivot resolver and direct Transformers 4/5 MT adapter; VAD-gated on-demand Cohere adapter; buffered voice output and bidi display helpers. 118 tests pass on the new runtime. | Wire bilingual routing/assembly/glossary/Cohere into live sessions and GUI; TranslateGemma; graphical display/pass-through and end-to-end acceptance checks. Cohere weights still require model authorization before speed/accuracy can be measured. |
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
