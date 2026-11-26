# V3 languages and landing implementation

Work stays on `codex/v3-languages-landing` in draft PR #21. No main push,
deployment, installers, releases, real provider calls or model downloads.
All non-English site copy and language examples require native review.

L0: supplied handoff and five landing WebPs preserved. Baseline: 504 tests pass.

A1: one catalog of 19 script-specific entries (18 base languages), ordered with
14 site priorities and the five retained languages. GUI, language/script groups,
speech cultures, sample configuration and reply aliases read it. Spanish and
Portuguese default to Mexican and Brazilian varieties; saved explicit varieties
are retained for the pair. `tools/site_languages.py` generates the site data.
Verification: `python -m pytest -q` â€” 524 tests pass. Consumer/export drift tests
cover ordering, legacy aliases, Chinese script identity and Norwegian `no`/`nb`.

A2: dated capability references for all ten providers; complete ISO-639-3 mapping;
Norwegian Whisper aliases and Chinese script-aware routing, preferences and
translation requests. Enhanced Speechmatics selects a verified bilingual pack
or one source language; Melia uses individual hints. Verified new OPUS metadata
is pinned by revision, including Mandarin target tokens for Hans/Hant; unverified
standard directions remain unavailable. TranslateGemma coverage follows the
official model card code map. No inference/quality claims were made.
Verification: `python -m pytest -q` — 573 tests pass. The shared Tcl fixture
retries only the runner's transient shared-script read error, matching the UI fixture.

A3: script-specific Tk fonts across transcript, captions and reply trays; measured
character wrapping for Han/kana display copies, including resizing. Stored text
stays unchanged. Full-width sentence ends flush promptly; glossary terms match
next to Han/kana without matching inside Latin words.
Verification: full `python -m pytest -q` — 583 pass; focused typography/UI suite
— 20 pass, including the added CJK transcript font/preservation integration check.
