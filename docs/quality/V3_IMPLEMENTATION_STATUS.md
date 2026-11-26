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

A4: yes/moment/repeat phrasebooks cover all 19 entries, with Appendix C repeat
phrases and ASCII Pinyin, Hepburn and Revised Romanization. Cloud reply prompts
name the catalog romanization system and Chinese target script.
Verification: `python -m pytest -q` — 607 tests pass, including all phrasebooks
against every audience language and the eight-word/readability constraints.

A5: 27 public FLEURS clips pinned across nine subsets (Dutch, Norwegian, Polish,
Swedish, Mandarin, Japanese, Korean, Latin American Spanish and Brazilian
Portuguese), with dataset revision, clip IDs, published references and SHA-256.
Traditional Chinese reuses Mandarin and labels its published Hans reference.
The loader rejects revision, metadata, length and hash drift before inference.
Only temporary evaluation audio was fetched; no audio was added to Git.
Verification: `python -m pytest -q` — 621 tests pass; pinned-loader tests cover
all ten app choices and integrity failures using synthetic bytes.

A6: Windows voices are filtered by catalog language and Chinese locale, accepting
legacy LCID/byte metadata and Norwegian aliases. Automatic synthesis selects a
matching voice; Piper and SAPI never fall back to another language. Missing
voices show the requested hint and a Windows speech-settings link in Audio.
Stale asynchronous voice results cannot overwrite a new audience choice.
Verification: `python -m pytest -q` — 645 tests pass with fake voice lists only.
No voices or models were installed, and no physical audio devices were used.
