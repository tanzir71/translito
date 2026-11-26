# V3 native review — pending

All non-English copy and examples are drafts. No locale or language-page example
is marked reviewed. The owner arranges review before merging, as required by
section 6 of CODEX_HANDOFF_V3_LANGUAGES_LANDING.md.

Check meaning, natural wording, politeness, the Mexican/Brazilian defaults,
Simplified/Traditional characters, and pronunciation of ASCII reply readings.
Confirm all replies remain at most eight spoken words. The latest instruction
sets every non-English home example to English speech translated into the page's
language, with a matching target language in the app notice. The English home
shows Arabic → English. English language pages also show native → English.

| Locale | Draft home copy | Draft language-page examples | Reviewed |
|---|---|---|---|
| de | [copy](../../website/i18n/de.toml) | [examples](../../website/data/language_pages/german.json) | No |
| es-mx | [copy](../../website/i18n/es-mx.toml) | [examples](../../website/data/language_pages/spanish.json) | No |
| fr | [copy](../../website/i18n/fr.toml) | [examples](../../website/data/language_pages/french.json) | No |
| nl | [copy](../../website/i18n/nl.toml) | [examples](../../website/data/language_pages/dutch.json) | No |
| nb | [copy](../../website/i18n/nb.toml) | [examples](../../website/data/language_pages/norwegian.json) | No |
| pl | [copy](../../website/i18n/pl.toml) | [examples](../../website/data/language_pages/polish.json) | No |
| pt-br | [copy](../../website/i18n/pt-br.toml) | [examples](../../website/data/language_pages/portuguese.json) | No |
| sv | [copy](../../website/i18n/sv.toml) | [examples](../../website/data/language_pages/swedish.json) | No |
| ar | [copy](../../website/i18n/ar.toml) | [examples](../../website/data/language_pages/arabic.json) | No |
| zh-cn | [copy](../../website/i18n/zh-cn.toml) | [examples](../../website/data/language_pages/chinese-simplified.json) | No |
| zh-tw | [copy](../../website/i18n/zh-tw.toml) | [examples](../../website/data/language_pages/chinese-traditional.json) | No |
| ja | [copy](../../website/i18n/ja.toml) | [examples](../../website/data/language_pages/japanese.json) | No |
| ko | [copy](../../website/i18n/ko.toml) | [examples](../../website/data/language_pages/korean.json) | No |

Review the shared app [phrasebook](../../engines/data/replies.json) too. Public
FLEURS references are published source text, not new translations. Traditional
Chinese reuses Mandarin audio with an explicitly marked Simplified reference.

The owner requested direct integration into main and Pages publication. Native
review remains pending. No native app build, installation, physical-device check,
provider inference or model download was performed for V3.

Automated checks use Python/pytest, Hugo 0.121.0 extended and Node for the small
JavaScript geometry contract. Hugo lives in ignored tools/bin or may be supplied
with TRANSLITO_HUGO. Site builds write only into temporary folders.
