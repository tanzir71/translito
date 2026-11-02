# Translation-quality implementation

Specification: `CODEX_HANDOFF_TRANSLATION_QUALITY.md` supplied by the owner.
Native macOS code is outside this change.

| Phase | Current evidence | Remaining work |
|---|---|---|
| P0 evaluation | Shared desktop replay, WER/CER/chrF and bilingual metrics, latency/RAM/cost reports, cache-only socket-blocked run; see P0_BASELINE.md | Cohere hardware measurements after runtime upgrade and gated access. Saudi meeting set waived by owner; those accuracy targets are unverified. |
| P1 local quality | Tested routing/LID policy, 186-term additive glossary, span protection, byte-preserving config migration, shared hallucination guards, VAD endpointing, sentence assembler, unbounded speech queue with lag events, four-beam MT, turbo alias resolution and CPU/CUDA faster-whisper selection. 96 tests pass. | Wire bilingual routing/assembly/glossary into live sessions and GUI; Cohere/fallback loading and runtime upgrade; local MT resolution/TranslateGemma; display/pass-through and end-to-end acceptance checks. |
| P2 provider infrastructure | Engine contracts and pure usage-cost calculation only | Router/fallback, durable history/caps, Credential Manager, settings/test flows and engine chip. |
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
