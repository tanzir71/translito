# Codex Handoff: priority languages in the app, and the new translated website

Date: 2026-11-26. Baseline: `main` with v2 complete (M0–M8.2, tip `3a35cd5` or later). This is a delta on top of `CODEX_HANDOFF_V2_SPEED_COST_UX.md`; that file's ground rules still apply unless this one changes them.

## Goal

1. **App:** add Dutch, Norwegian (Bokmål), Polish, Swedish, Chinese (Simplified and Traditional), Japanese and Korean. Spanish and Portuguese default to the Mexican and Brazilian varieties. Italian, Russian, Turkish, Persian and Urdu stay supported. Arabic → English stays the benchmark pair.
2. **Website:** build the redesigned landing page from Figma, translated into 14 site languages with a language picker, plus one English page per priority language.

The owner's words: "Arabic is the benchmark, but optimise the landing page for every other language, like you did for Saydraft." Then, with a screenshot of a 14-language picker: "these languages are priority." He chose: translate the site into these 14 **and** add the missing languages to the app; keep Italian, Russian, Turkish, Persian and Urdu "listed after, without their own translated site or page for now".

### Priority languages (site locales, in this order)

| Site code | Native name | English name | App language | Script, direction |
|---|---|---|---|---|
| en | English | English | en | Latin |
| de | Deutsch | German | de | Latin |
| es-mx | Español (México) | Spanish | es, variety es-MX | Latin |
| fr | Français | French | fr | Latin |
| nl | Nederlands | Dutch | nl (new) | Latin |
| nb | Norsk | Norwegian | nb (new; Whisper code `no`) | Latin |
| pl | Polski | Polish | pl (new) | Latin |
| pt-br | Português (Brasil) | Portuguese | pt, variety pt-BR | Latin |
| sv | Svenska | Swedish | sv (new) | Latin |
| ar | العربية | Arabic | ar | Arabic, right to left |
| zh-cn | 简体中文 | Chinese, Simplified | zh, script Hans (new) | Han |
| zh-tw | 繁體中文 | Chinese, Traditional | zh, script Hant (new) | Han |
| ja | 日本語 | Japanese | ja (new) | Kanji and kana |
| ko | 한국어 | Korean | ko (new) | Hangul |

Also supported, listed after the 14, no translated site or page: Italiano, Русский, Türkçe, فارسی, اردو.

## Read these first

- Figma file "Translator", page **Translito v2 · Landing**: https://www.figma.com/design/qHi2n6YF49UURgSJPYb6tB/Translator?node-id=24-2 . All copy is also in the appendix, so Figma access is optional.

  | Frame | Node |
  |---|---|
  | Landing · Desktop 1440 | 24:44 |
  | Landing · Mobile 390 | 28:249 |
  | Language picker · open | 35:369 |
  | Localized · Arabic, right to left | 36:383 |
  | Localized · Japanese | 36:489 |
  | Language page · Spanish (template) | 32:314 |
  | Languages · site and pages (spec) | 37:484 |
  | Type scale | 28:431 |
  | Web components (buttons, tag, language chip, picker) | frame "Web components" |

- Product images, already in the repo: `website/static/img/landing/` → `hero-meeting.webp` (2560×1440, meeting and taskbar only), `subtitles-settings.webp`, `schedule-settings.webp`, `engine-settings.webp`, `languages-settings.webp` (each 1200 wide, shown at 600).
- Website: `website/hugo.toml`, `website/layouts/index.html`, `website/layouts/_default/baseof.html`, `website/static/css/style.css`, `.github/workflows/hugo.yml` (Hugo 0.121.0 extended).
- App: `gui.py` (`LANGUAGES`), `engines/lid.py` (`LATIN_LANGUAGES`), `engines/mt_cloud.py` (`LANGUAGES`), `engines/data/opus_pairs.json`, `engines/data/translategemma.json` (`supported_languages`), `engines/streaming_protocols.py` (ElevenLabs maps only `ara`/`eng`; Speechmatics hard-codes `ar_en` for Enhanced), `engines/registry.py` (`source_languages`), `engines/replies.py` and `engines/data/replies.json`, `engines/checks.py` (sample catalogs), `engines/sentence_assembler.py`, `engines/display.py`, `engines/protect.py`.

## Ground rules

- **Work unattended, automated tests only.** `python -m pytest -q` plus the Hugo build checks in W1. No manual checks, devices, installers or clicking through the app or site.
- **No real keys, no paid or cloud calls.** Provider adapters are tested with mocks, as in v2.
- **No model weights downloaded.** Reading Hugging Face metadata to confirm that a model repo and revision exist is fine. Small public evaluation clips may be fetched once to pin their hashes (A5); do not commit audio.
- **Translations are drafts.** Codex drafts every non-English string. Each locale file starts with a comment saying it is a draft for native review, and `hugo.toml` sets `reviewed = false` per language. The owner arranges native review (section 6). Use the reference strings in the appendix where given.
- **Git, same as v2, stricter on `main`.** Branch `codex/v3-languages-landing` from the current `main`. Commit and push after every milestone, run `python -m pytest -q` before each push, open one **draft** pull request and tick the milestone checklist in it.
  - The v2 milestones M1.3–M8.2 were pushed straight to `main` with `[skip ci]`. Do not do that here: pushing website changes to `main` deploys the site, and `[skip ci]` is not a substitute for staying on the branch.
  - Never push to `main`, merge, mark the pull request ready, tag, release, dispatch a workflow or edit `.github/workflows/`.

## 1. Milestones

| ID | Scope | Done when |
|---|---|---|
| L0 | Commit this handover; open the draft pull request | Pushed |
| A1 | One language catalog for the app | Every consumer reads it; a test fails on any hard-coded language set |
| A2 | Engines per language: capabilities, codes, local pairs | Registry and contract tests per pair |
| A3 | Text handling for CJK and new Latin languages | Font, wrap, punctuation and protection tests |
| A4 | Replies: phrasebook and romanization for the new languages | Parse and phrasebook tests per language |
| A5 | Speed and accuracy check samples for the new languages | Catalog entries pinned, loader tests |
| A6 | Speak mode voices for the new languages | Missing-voice hint tested with a fake voice list |
| W1 | Hugo multilingual setup, picker, hreflang | Hugo build test passes |
| W2 | English landing page from Figma | Build test checks every section and image |
| W3 | 13 translated home pages | Build test: 14 homes, lang and dir right, no missing strings |
| W4 | 13 English language pages | Build test: 13 pages, titles, links |
| W5 | Type per script, right to left, mobile | CSS and build tests |

## 2. App milestones

### A1. One language catalog

Create `engines/languages.py` as the single source: code, English name, native name, script (`latin`, `arabic`, `han`, `japanese`, `hangul`, `cyrillic`), right to left, Whisper code, BCP-47 for speech output, default variety, `romanize_replies`, site locale (or none) and priority. Derive everything else from it: `gui.LANGUAGES`, `lid.LATIN_LANGUAGES`, `mt_cloud.LANGUAGES`, picker lists, check catalogs, reply rules, and `website/data/languages.json` (write a small `tools/site_languages.py` and test that the site data matches the catalog).

- New entries: `nl`, `nb` (Whisper `no`), `pl`, `sv`, `zh` with script variants Hans and Hant shown as "Chinese, Simplified" and "Chinese, Traditional", `ja`, `ko`.
- Varieties: Spanish defaults to `es-MX` and Portuguese to `pt-BR`; `es-ES` and `pt-PT` stay selectable through the existing variety setting.
- Order in pickers: the 14 priority languages in the table order, then the five others.
- Keep `config.ini` values working: existing codes map unchanged.

### A2. Engines per language

- Fill each provider's supported languages in the capability registry from its public docs, with the date checked: Soniox, ElevenLabs, Speechmatics, Gemini, Azure, DeepL, Google, Groq, Cohere, Gemini Live. An unsupported pair stays listed as unavailable with its reason.
- `ElevenLabsProtocol`: map every catalog language between ISO 639-3 and the app's codes (`deu`, `spa`, `fra`, `nld`, `nor`/`nob`, `pol`, `por`, `swe`, `zho`/`cmn`, `jpn`, `kor`, plus the existing ones), not only `ara` and `eng`.
- `SpeechmaticsProtocol`: Enhanced uses a bilingual pack only where one exists for the pair (`ar_en` today); otherwise use the single-language code or Melia with language hints.
- Chinese: request Simplified or Traditional output explicitly from every translator (for example `zh-Hans` or `zh-Hant`, or the provider's equivalent) according to the target. Show recognized Chinese source text as recognized; do not add a script-conversion dependency.
- Local translation: for each new pair with English in both directions, look up a Helsinki-NLP repository and revision (metadata only) and add it to `opus_pairs.json`. Where none exists, record it under `unavailable_standard_pairs`; the Engine page then shows "needs a cloud engine" for that pair. Extend TranslateGemma's `supported_languages` only for languages its model card lists.
- Tests: router and registry resolution for each new pair; mock contract tests for the new codes.

### A3. Text handling

- `LATIN_LANGUAGES` comes from the catalog (adds `sv`, `nb`/`no`).
- Sentence ends: add `！` and `？`, keeping `。`, `?`, `!`, `.` and `؟`.
- Term protection and glossary matching must not assume spaces between words in Chinese and Japanese.
- Fonts in the Tk app, per script, for transcript rows, the subtitle bar and the reply tray: Latin and Arabic keep the current fonts; Simplified "Microsoft YaHei UI", Traditional "Microsoft JhengHei UI", Japanese "Yu Gothic UI", Korean "Malgun Gothic". Wrap Chinese and Japanese by character.
- Tests for font choice, wrapping and sentence ends with fixtures in each new script.

### A4. Replies

- `engines/data/replies.json`: add `yes`, `moment` and `repeat` for every new language. Use the "repeat" strings in appendix C; draft the others.
- Romanization in plain ASCII without tone marks or accents: Chinese pinyin, Japanese Hepburn, Korean Revised Romanization. Name the system per language in the cloud reply prompt in `mt_gemini.py`.
- Tests: `parse_replies` and `phrasebook` for every catalog language, including the eight-word limit.

### A5. Check samples

Add public samples with reference text for the new languages to the check catalog, for example the FLEURS subsets `nl_nl`, `nb_no`, `pl_pl`, `sv_se`, `cmn_hans_cn`, `ja_jp`, `ko_kr`, plus `es_419` and `pt_br` for the new default varieties. Pin dataset revision, clip IDs and hashes. For Traditional Chinese, reuse the Mandarin clips and give a Traditional reference only if a published one exists; otherwise mark the reference as Simplified.

### A6. Speak mode voices

List Windows voices per catalog language. When none is installed for the audience language, show "No Windows voice for <language>. Add one in Windows speech settings." with a link. Never install anything. Test with a fake voice list.

## 3. Website milestones

### W1. Hugo multilingual setup and picker

- `hugo.toml`: `defaultContentLanguage = "en"`, `defaultContentLanguageInSubdir = false`, and 14 `[languages.<code>]` blocks in the table order with `languageName` (native name), `languageCode` (BCP-47) and `weight`. `ar` gets `languageDirection = "rtl"`. Strings go in `website/i18n/<code>.toml`.
- `baseof.html`: `<html lang dir>`, a `<link rel="alternate" hreflang>` for each of the 14 plus `x-default`, translated title and description, and the existing Open Graph tags per language.
- **Picker** (frame 35:369): nav button showing the current code; menu headed "LANGUAGE" listing the 14 native names with codes, a mint marker on the current one, and "REMEMBERED ON THIS DEVICE" at the bottom.
  - Plain links, so it works without JavaScript.
  - A small script stores the choice in `localStorage` (wrapped in try/catch) and, on the English home page only, sends a returning visitor to their stored locale.
  - Never redirect on browser language alone.
  - Keyboard and screen-reader accessible: button with `aria-expanded`, list of links, Escape closes.
- Build test: `tests/test_site_build.py` runs Hugo 0.121.0 extended into a temporary folder and checks:
  - 14 home pages, each with the right `lang`, `dir` and complete hreflang set;
  - no missing i18n keys (`--printI18nWarnings` prints nothing);
  - the string "50+" appears nowhere.

  If Hugo is not installed, download that exact version into an ignored `tools/bin/` folder; do not install it system-wide.
- Leave `website/public/` alone; the Pages workflow builds from source.

### W2. English landing page (frames 24:44 and 28:249)

Rebuild `layouts/index.html` and `style.css` from the desktop and mobile frames.

- **Sections in order:** nav, hero, "New on Windows" overview, five feature sections, "Also in Translito", languages, "Set it up once", questions, download, footer. Copy is in appendix A.
- **Type scale (frame 28:431):**
  - hero heading `clamp(2.125rem, 3.4vw, 3rem)`, weight 600, line height 1.125;
  - section heading `clamp(1.625rem, 2.4vw, 2rem)`;
  - card heading 1.25rem; lead 1.125rem; body 1rem; small 0.875rem;
  - label 0.8125rem in sentence case;
  - heading letter spacing −0.02em.

  Load Funnel Display weights 400, 500 and 600 only.
- **Palette:** the existing variables plus `--ink-line #262c27`, `--on-ink #f3f5f1` and `--on-ink-muted #b7bdb6`.
- **Hero:** `hero-meeting.webp` with the subtitle bar, its hover controls and the start notice drawn in HTML and CSS on top, so their text can be translated. The bar has two lines: previous and current. The notice reads "Weekly sync is starting" / "Subtitles are on, translating into {language}." with Stop and Settings buttons; it stays in English on every locale because the app is not translated, with only the language name changing. On mobile, crop the same image with `object-position`.
- **Feature images:** the four settings WebP files, the same on every locale, with translated `alt` text. Lazy-load everything below the hero.
- **Reply card (feature 3):** HTML. On the English page, show the four-language card from appendix A. On translated pages, show three English replies with their meaning in the page's language; that is what a reader of that language sees in English meetings.
- **Languages section:** the 14 priority languages with native and English names, linking to their language pages, then "Also supported" with the five others as plain text, then the accuracy note.
- **Footer:** "Translito in" links to the 14 translated home pages. Remove the old version line.
- Build test: every section id is present (`features`, `how`, `cost`, `download`), every image path resolves, every language link resolves.

### W3. Translated home pages

- Same structure and images as the English page; only strings change. No locale-only sections.
- **Example direction:** the subtitle bar shows English speech translated into the page's language. Use the reference Arabic and Japanese hero strings in appendix B, and draft the rest in the same way.
- Keep "Windows", "macOS", "Zoom", "Teams", "Meet", "Translito" and shortcut names untranslated.

### W4. English language pages (frame 32:314)

- `/languages/<slug>/` for the 13 non-English priority languages, in English, generated from `website/data/languages.json` and one data file per language. Slugs are in appendix C; there is no page for English or for the five "Also supported" languages.
- **Each page:**
  - hero with that language's subtitle bar (original line above the English translation) and reply tray in HTML over `hero-meeting.webp`;
  - "What it looks like in {Language}": three sample lines, one keeping an English term;
  - "Reply in {Language}": three replies of at most eight words, polite, one asking to repeat, in English letters for non-Latin scripts;
  - "How well it works in {Language}", with the benchmark sentence;
  - other languages, with the current one marked;
  - download and footer.
- Spanish uses appendix B exactly; draft the others.
- **Title:** "Translito for {Language}: live {Language} and English meeting subtitles".
- **Description:** "Live subtitles between {Language} and English over Zoom, Teams or Meet on Windows. Short replies in {Language}{, written in English letters}. Free on your PC, with optional pay-as-you-go cloud engines."
- **Home title:** "Translito: live meeting subtitles in 18 languages for Windows and macOS". Replace `seoTitle` in `hugo.toml`.

### W5. Type per script, right to left, mobile

- **Latin locales:** Funnel Display. Check that Google Fonts serves its Latin Extended subset (Polish, Norwegian, Swedish letters); if not, fall back to `system-ui` for those characters.
- **Arabic:** `"Janna LT", "Noto Sans Arabic", Tahoma, sans-serif`, loading Noto Sans Arabic from Google Fonts on the Arabic pages only.
  - Heading 46px with 72px line height; body 18px with 32px.
  - Mirror the layout with logical properties (`margin-inline`, `padding-inline`, `inset-inline`); the nav order and button order flip, as in frame 36:383.
  - Do not mirror images.
  - Wrap Latin words (Windows, macOS, API) in `<bdi>`.
- **Chinese, Japanese and Korean:** system font stacks with no web font download:
  - Simplified: `"PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif`
  - Traditional: `"PingFang TC", "Microsoft JhengHei", "Noto Sans TC", sans-serif`
  - Japanese: `"Hiragino Sans", "Yu Gothic", "Noto Sans JP", sans-serif`
  - Korean: `"Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif`

  Headings 42px, weight 500, line height 1.43, letter spacing 0; body line height 1.8; `word-break: keep-all` for Korean, as in frame 36:489.
- **Cyrillic:** appears only in "Also supported" (Русский); add `Inter, system-ui` to the stack.
- **Mobile:** frame 28:249 sizes: hero heading 34px, section heading 26px, full-width buttons.

## 4. Done means (automated)

- `python -m pytest -q` passes at every pushed milestone, including `tests/test_site_build.py`.
- The app catalog has 19 entries (Chinese counted once per script); every consumer reads it.
- Every new language pair resolves to an engine or shows its reason; mock contract tests cover the new codes.
- The site builds 14 home pages and 13 language pages with correct `lang`, `dir`, hreflang, titles and descriptions; no missing strings; no "50+".

## 5. Pitfalls

- Do not push to `main`, merge, tag, release or dispatch a workflow. Website changes on `main` deploy the site.
- Do not show a language on the site that the app catalog does not have; the site data is generated from it.
- Do not redirect visitors by browser language.
- Do not mirror screenshots on right-to-left pages, and do not use negative letter spacing on Chinese, Japanese or Korean.
- Do not hard-code language lists anywhere new.
- Do not present draft translations as reviewed.

## 6. Left for the owner (not for Codex)

- Native review of every translated page, language page, sample line and reply before merging.
- Choosing whether to keep the localarabic.com domain.
- Merging the pull request, which deploys the site.

## Appendix A. English copy (home page)

**Nav:** Translito · Features · How it works · Cost · Download · [picker: EN] · Download

**Hero**
- Label: Live translation for Windows and macOS
- Heading: Follow every meeting in your language.
- Lead: Translito listens to your meeting app and shows the translation as subtitles over any window, even when the app is minimized. 18 languages, in either direction, with English terms kept as spoken.
- Buttons: Download for Windows · Download for macOS
- Small: Free on your PC. Cloud engines are optional, and you pay only for speech.
- Product shot overlay:
  - subtitle bar: "The deployment slipped two days because of an API issue." / "When can we deliver the first version?"
  - notice: "Weekly sync is starting" / "Subtitles are on, translating into English." / Stop · Settings

**Overview**
- Label: New on Windows
- Heading: Built for live meetings.
- Items:
  - Subtitles on screen: Over any window, even with Translito minimized.
  - Starts with your meeting: From a calendar link or set times, in your usual meeting app.
  - Reply in their language: Short replies in English letters, with what they mean.
  - Clear cost and speed: See the delay and cost of each engine. Set a monthly budget.

**Feature 1: Subtitles that stay on top** (image: subtitles-settings)
- Keep the meeting full screen and Translito in the tray. The translation sits in a slim bar over everything, with the previous line above the current one.
- Clicks pass through, so the meeting stays usable
- Drag it anywhere; its place is remembered for each screen
- Switch it on from the app, the tray, a shortcut or settings
- Text size, number of lines and the original line are your choice

**Feature 2: Starts when your meeting does** (image: schedule-settings, image on the left)
- Paste your calendar's private link or set weekly times. Translito starts a minute before, listens to your default meeting app and stops when the meeting ends.
- Waits until the meeting app plays sound, so a no-show costs nothing
- Your meeting app is remembered: Zoom, Teams or a browser
- A notice with Stop appears at every automatic start

**Feature 3: Reply in their language** (HTML card)
- When someone asks you something, Translito suggests three short replies in their language, written in English letters with the meaning underneath.
- Say one with Ctrl + Alt + 1, 2 or 3, through Speak mode
- Shortcuts are yours to change
- Shown under the subtitle bar too, so they work with the app minimized
- A small built-in phrasebook covers you without a cloud engine
- Card (English page only):
  - Title: "Could you repeat the question?"
  - Subtitle: "The same suggested reply in four languages"
  - Arabic: "Mumkin tiid as-sual?" / ممكن تعيد السؤال؟
  - Russian: "Mozhete povtorit vopros?" / Можете повторить вопрос?
  - Urdu: "Kya aap sawal dohra sakte hain?" / کیا آپ سوال دہرا سکتے ہیں؟
  - Spanish: "¿Puede repetir la pregunta?" / "Latin script, so the reply is shown as written"
  - Footnote: "Languages written in another script also get the reply in English letters, so you can say it."

**Feature 4: Know the cost and speed before you choose** (image: engine-settings; anchor `cost`)
- Run Translito free on your PC, or connect a cloud engine with your own key when you need more speed and accuracy. You pay the provider directly, only for the speech Translito sends.
- A built-in check measures delay and accuracy on your PC
- Silence, music and other languages are never sent
- A monthly budget you set, then back to your PC or stop
- Choose your default provider and model for each language pair

**Feature 5: Settings that make sense, and stay put** (image: languages-settings, image on the left)
- Settings are grouped by what you are doing: languages, engine, cost, subtitles, schedule and audio. Every switch and choice is saved the moment you change it.
- One picker for what is spoken and what you want to read
- English spoken in the meeting is shown as is, never translated
- Your own terms list for names and jargon

**Also in Translito**
- Speak into calls: Your translated voice goes into Zoom, Teams or Meet through a virtual microphone.
- Any app's audio: Listen to one app, or to everything your computer plays.
- Transcripts, saved: Every session is saved with timestamps in a folder you choose.
- Private on your PC: On this PC, nothing leaves your computer once the models are downloaded.
- Shortcuts you choose: Start, stop, subtitles and replies, all recordable.
- Menu bar and tray: Controls stay one click away on macOS and Windows.

**Languages**
- Heading: 18 languages, in either direction
- Intro: Pick any two. English spoken in the meeting can pass through as is. Chinese works in Simplified and Traditional characters.
- List: the 14 priority languages, native name then English name.
- "Also supported": Italiano, Русский, Türkçe, فارسی, اردو
- Note: Coverage and measured accuracy are separate. Arabic to English is the pair we measure on every release. For any other pair, the built-in check measures delay and accuracy on your own PC before you pay for anything.

**Set it up once** (anchor `how`)
1. Install: A Windows installer or portable ZIP, or one universal app for Mac.
2. Choose languages and your app: Pick what is spoken and what you want to read. Translito remembers both.
3. Join your meeting: Press Start, or let your schedule start it. Subtitles appear on top.

**Questions**
- Which languages work? English, German, Spanish, French, Dutch, Norwegian, Polish, Portuguese, Swedish, Arabic, Chinese (Simplified and Traditional), Japanese and Korean, plus Italian, Russian, Turkish, Persian and Urdu, in either direction. Arabic to English is measured on every release; the check measures any other pair on your PC.
- Do I have to pay? No. On this PC Translito is free. Cloud engines are optional: you add your own key, pay the provider only for the speech Translito sends, and set a monthly budget.
- Does it work with Zoom, Teams and Meet? Yes. Choose your meeting app once and Translito listens to its audio. For meetings in a browser, it listens to the browser.
- Where does my audio go? On this PC, nowhere. With a cloud engine, only speech in your two languages goes to the provider you connected.

**Download** (anchor `download`)
- Label: Latest release
- Heading: Download Translito
- Windows card:
  - "Windows 10 and 11, 64-bit"
  - buttons: Download installer · Portable ZIP
  - note: "Includes subtitles on screen, schedule, reply suggestions and cost controls."
- macOS card:
  - "macOS 26.4 or later, Apple silicon and Intel"
  - button: Download for macOS
  - note: "Listen, Speak and saved transcripts. The features listed under New on Windows are not in the Mac app."
- Notice row: These builds are not code-signed yet, so Windows or macOS may warn you on first launch. · Show what to do (expands the existing first-launch steps)
- Download links stay the release links in the current `index.html`; read the version from `hugo.toml`.

**Footer**
- Translito · Live translation for your desktop. Built by Tanzir in Bangladesh.
- Links: Features · Download · GitHub · tanziro.com
- "Translito in" with the 14 native names.

## Appendix B. Reference translations (drafts for native review)

**Arabic home hero (frame 36:383)**
- Nav: الميزات · طريقة العمل · التكلفة · التنزيل · button تنزيل
- Label: ترجمة فورية لنظامي Windows وmacOS
- Heading: تابع كل اجتماع بلغتك.
- Lead: يستمع Translito إلى تطبيق الاجتماعات ويعرض الترجمة نصًا على الشاشة فوق أي نافذة، حتى عندما يكون التطبيق مصغّرًا. 18 لغة في الاتجاهين، مع إبقاء المصطلحات الإنجليزية كما قيلت.
- Buttons: تنزيل لنظام Windows · تنزيل لنظام macOS
- Small: مجاني على جهازك. محركات السحابة اختيارية، وتدفع فقط مقابل الكلام.
- Subtitle bar: تأخر الإطلاق يومين بسبب مشكلة في الـ API. / متى يمكننا تسليم النسخة الأولى؟
- Notice: "Subtitles are on, translating into Arabic."

**Japanese home hero (frame 36:489)**
- Nav: 機能 · 使い方 · 料金 · ダウンロード · button ダウンロード
- Label: Windows と macOS のリアルタイム翻訳
- Heading: すべての会議を、あなたの言語で。
- Lead: Translito は会議アプリの音声を聞き取り、翻訳を字幕としてどのウィンドウの上にも表示します。アプリを最小化していても表示されます。18 言語に双方向で対応し、英語の専門用語は話されたまま残します。
- Buttons: Windows 版をダウンロード · macOS 版をダウンロード
- Small: PC 上では無料。クラウドエンジンは任意で、話した分だけ支払います。
- Subtitle bar: API の問題でデプロイが 2 日遅れました。 / 最初のバージョンはいつ納品できますか？
- Notice: "Subtitles are on, translating into Japanese."

**Spanish language page (frame 32:314), English page**
- Label: Languages / Spanish
- Heading: Live subtitles between Spanish and English.
- Lead: Translito listens to Zoom, Teams or Meet and shows what is said in Spanish as English subtitles over any window. It works the other way too, from English into Spanish.
- Buttons: Download for Windows · macOS
- Hero bar: ¿Podemos mantener la entrega del jueves? / Can we keep the Thursday delivery?
- Hero replies:
  1. Sí, el jueves está bien: Yes, Thursday is fine
  2. Deme dos días y le confirmo: Give me two days and I will confirm
  3. ¿Puede repetir la pregunta?: Could you repeat the question?
- "What it looks like in Spanish". Intro: English words that people say inside Spanish, like deployment or API, are kept as spoken. Columns "Said in the meeting" | "Your subtitle":
  - Vamos a revisar el presupuesto del trimestre. | Let's review the budget for the quarter.
  - El deployment se retrasó dos días por un problema con la API. | The deployment slipped two days because of an API issue.
  - ¿Podemos mantener la entrega del jueves? | Can we keep the Thursday delivery?
- "Reply in Spanish". Intro: After a question, Translito suggests three short replies. Say one with Ctrl + Alt + 1, 2 or 3. Cards: the three hero replies. Note: Spanish uses the Latin alphabet, so replies are shown as written. In Arabic, Chinese, Japanese, Korean and the other languages with their own script, replies also come in English letters.
- "How well it works in Spanish": Arabic to English is the pair we measure on every release. Spanish uses the same features and engines. Before you choose an engine, the built-in check plays public Spanish clips through each one and shows the delay, accuracy and cost on your own PC. Button: See the speed and accuracy check.
- "Other languages": the languages list with Spanish marked.

## Appendix C. Language pages and the "repeat" reply

| Language | Slug | Reply "Could you repeat the question?" | In English letters |
|---|---|---|---|
| German | german | Können Sie die Frage wiederholen? | (Latin) |
| Spanish | spanish | ¿Puede repetir la pregunta? | (Latin) |
| French | french | Pouvez-vous répéter la question ? | (Latin) |
| Dutch | dutch | Kunt u de vraag herhalen? | (Latin) |
| Norwegian | norwegian | Kan du gjenta spørsmålet? | (Latin) |
| Polish | polish | Czy można powtórzyć pytanie? | (Latin) |
| Portuguese | portuguese | Pode repetir a pergunta? | (Latin) |
| Swedish | swedish | Kan du upprepa frågan? | (Latin) |
| Arabic | arabic | ممكن تعيد السؤال؟ | Mumkin tiid as-sual? |
| Chinese, Simplified | chinese-simplified | 可以请您重复一下问题吗？ | Keyi qing nin chongfu yixia wenti ma? |
| Chinese, Traditional | chinese-traditional | 可以請您重複一下問題嗎？ | Keyi qing nin chongfu yixia wenti ma? |
| Japanese | japanese | 質問をもう一度お願いできますか？ | Shitsumon o mou ichido onegai dekimasu ka? |
| Korean | korean | 질문을 다시 한번 말씀해 주시겠어요? | Jilmuneul dasi hanbeon malsseumhae jusigesseoyo? |
