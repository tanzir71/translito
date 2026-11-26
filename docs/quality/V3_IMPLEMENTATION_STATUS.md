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

Verification: `python -m pytest -q` — 524 tests pass. Consumer/export drift tests

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



W1: 14 ordered Hugo locales with draft review flags, language/direction metadata,

14 hreflang alternates plus x-default, locale links and a progressively enhanced

picker. Plain links/native details work without JS; Escape/outside click close

the enhanced menu, and storage is guarded. Only a remembered choice redirects

the English home; browser language is never used. Locale text is scaffolded in

English pending W3. Exact Hugo 0.121.0 extended is in ignored tools/bin.

Verification: `python -m pytest -q` — 661 tests pass, including real Hugo builds

into temporary folders and all 14 home/metadata/picker checks. website/public

and workflows are untouched. New clones need the same Hugo binary in tools/bin

or PATH (or TRANSLITO_HUGO) before running site tests.



W2: English landing rebuilt from the desktop/mobile Figma responses, with a

1120px content grid, 600px settings images, the specified type/palette/spacing,

semantic subtitle/control/toast overlays and a four-language reply card. Exact

SVGs and WebPs have a dimensions/hash receipt. The hero scene scales/crops to

the 1440/390 design dimensions; downloads use the existing configured version

and retain separate macOS scope and expandable first-launch instructions.

English language-page introductions are scaffolded so all catalog links resolve;

W4 will add their complete data/examples. Non-English strings remain scaffolded

pending W3. No manual app/site checks were performed, as requested.

Verification: `python -m pytest -q` — 664 tests pass; real Hugo build has no

i18n/layout warnings. Build tests check sections, images, language links, source

asset hashes/dimensions and JavaScript hero geometry. public/workflows untouched.


W3: all 131 strings are drafted in each of the 13 non-English locales, including
metadata, feature copy, alt text, first-launch guidance and reply meanings.
Arabic/Japanese reference heroes are verbatim; Chinese scripts use distinct
localized examples. Each page retains the English app notice and three English
replies with page-language meanings. Every locale begins with the native-review
comment and all review flags remain false. SVGs are exempt from line-ending
conversion so their source hashes remain stable on Windows checkouts.
Verification: `python -m pytest -q` — 679 tests pass; real Hugo builds all 14
homes with no missing strings and checks complete localized content/metadata.

W4: 13 complete English language pages, generated metadata/frontmatter from the
shared catalog and one draft example-data file per language. Each includes three
native-to-English samples, polite short replies (ASCII romanization where needed),
the Arabic benchmark statement, marked current-language navigation and shared
downloads/footer. Spanish uses the supplied reference examples verbatim.
The latest user instruction changes the original W3 example direction: all
non-English home heroes now pair their native question with its English
translation, and every start notice says translating into English.
Verification: `python -m pytest -q` — 694 tests pass, including all 13 pages,
SEO, source/output language tags, short replies, generator drift, source assets
and the Figma language-page hero crop. No deployment or manual checks.

W5: catalog-driven script metadata selects the specified Arabic/CJK font stacks.
Arabic alone requests Noto Sans Arabic; CJK pages download no webfonts. Funnel
Display requests only 400/500/600; public metadata and CSS confirm Latin Extended
coverage. Arabic hero type is 46/72, CJK 42 at 500 with 1.43 leading and zero
tracking; mobile uses 34px hero and 26px section headings with full-width actions.
Logical layout properties mirror Arabic layout without mirroring screenshots,
and Latin terms are isolated with bdi. Korean keeps words together.
Final QA also surfaces unavailable Standard pairs before Start, marks the Live
preview's English-pair restriction, and triggers CJK replies on full-width ？.
Verification: `python -m pytest -q` — 719 tests pass. Real Hugo 0.121.0 extended
builds 14 homes and 13 English language pages with no missing i18n/layout warnings;
Node checks scene geometry, and asset hashes/dimensions remain intact. Catalog
export and JavaScript syntax checks pass. No manual checks or physical devices.

All V3 milestones are implemented on the draft branch. Native review of every
translation, example and reply remains pending; see V3_NATIVE_REVIEW.md. Domain
choice and merging/deploying remain owner tasks. No V3 installers, releases,
workflow changes or deployments were made. Remote main remains 74287b9.
