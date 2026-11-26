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
