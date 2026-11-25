# Codex Handoff: Translito v2 — speed, accuracy, clear cost, and UX

Date: 2026-11-25. Baseline: `main` at `7736e9b`, Windows 1.1.5, 406 tests passing.

## Goal

Make live translation fast and accurate enough to follow a meeting, make cost and performance visible before and during use, and replace the confusing settings with a structure a new user can read. **Arabic → English is the benchmark pair** that every number below is measured on, but nothing may be built Arabic-only: every feature has to work for any source/target pair through the same code path.

What the owner asked for, in his words:

1. "Translations are slow and not accurate. I'm fine with paying a little (pay as you go, only for actual usage; the app should filter real Arabic from noise so costs stay low) but costs and performance are not clear."
2. "Logo looks square black rather than being the shape of the icon."
3. "The settings page looks confusing. Design improved UX for the whole app."
4. "Arabic to English as benchmark but should apply to the use case of others as well."
5. "Translations should show as subtitles on the desktop even when the app is minimized, with an option to turn this on automatically based on scheduled meeting times."
6. "Short responses in the original language (phonetic in English) along with what it means", they "should also be able to be mapped to keyboard shortcut", and "should also show in subtitle mode if turned on."
7. "Should be able to set a default app, since most users have a default app for their meetings."
8. "Toggles like subtitles on screen, all of these should remember preferences."
9. "UI should allow setting default model/provider."
10. "Allow UI to set monthly budget."

## Read these first

- Figma file "Translator", page **Translito v2 · UX**: https://www.figma.com/design/qHi2n6YF49UURgSJPYb6tB/Translator?node-id=10-2 . Frame map is in section 11. Notes under each frame say what it replaces.
- `docs/quality/IMPLEMENTATION_STATUS.md`, `SAUDI_PUBLIC_ASR.md`, `LOCAL_HARDWARE.md`, `PAID_EVALUATION.md`, `BOOSTER_CONTRACTS.md`, `CLOUD_CONTRACTS.md`: what exists and what has been measured.
- `engines/registry.py`, `engines/router.py`, `engines/usage.py`, `engines/types.py`, `engines/live_pipeline.py`, `engines/conversation_pipeline.py`, `engines/sentence_assembler.py`, `audio_processing.py`, `engines/process_audio.py`.
- `tools/eval/streaming_protocols.py` and `tools/eval/streaming_runner.py`: the Soniox, Speechmatics and ElevenLabs wire contracts already written for evaluation.
- `gui.py` (`open_settings`, `build_ui`, `persist_settings`, `setup_tray`), `provider_settings.py`, `quality_settings.py`, `app_config.py`.
- `branding/translito-mark.svg` and `branding/translito-mark-small.svg`: icon masters added with this handoff.

## Ground rules

- **Work unattended.** Do not ask the owner to test, approve, install, sign up, reboot or supply anything, and do not wait for him. Everything left for him is in section 13; skip it.
- **Automated tests only.** Every milestone is verified with `python -m pytest -q` and nothing else. No manual checks, no physical devices (microphones, speakers, VB-CABLE), no installer builds or installs, no clicking through the app.
- **Cloud features: implement fully, no live testing.** No API keys will be provided. Build the provider adapters, streaming protocols, Connect dialog, cloud check and cloud reply generation from each provider's public docs and the existing eval contracts in `tools/eval/streaming_protocols.py`. Cover them with automated tests against mock transports and fixtures, like the existing contract tests, so the suite shows the app works end to end. The owner tests them live with his own keys later. Two tests matter most because they protect his money when he does: a $0 budget blocks every paid request (M4.2), and silence or music never opens a paid stream (M4.3).
- **No real keys and no paid or cloud calls.** Do not read Windows Credential Manager. Prices and model IDs here come from desk research on 25 Nov 2026: check them against each provider's public docs before hard-coding, and store the date checked next to every rate.
- **No new model downloads.** Local inference may run only against models already in the cache, with sockets blocked, as in earlier phases.
- Preserve user settings, transcripts and `usage.json`. Config changes are additive (`append_missing_settings`). The monthly budget default stays $0.
- Keys only in Windows Credential Manager at runtime. Test still gates enabling a provider.
- Do not report anything as verified that an automated test did not verify.

## Git: commit and push every milestone

The owner follows progress in the repo, so every milestone in the table below ends with a commit and a push.

1. Create one branch from `main` at `7736e9b`: `codex/v2-speed-cost-ux`. All work goes on it.
2. **Milestone M0** is the first commit: this handover and the `branding/` folder, exactly as provided. Push it.
3. Open one **draft** pull request from that branch to `main`, titled "Translito v2: speed, cost and UX". Put the milestone table in the description as a checklist.
4. For each milestone: finish it, run `python -m pytest -q` until it passes, commit with the milestone ID first (for example `M2.3 Languages page: one pair picker`), push, then tick the item in the pull request description and add one line on what changed. Small extra commits inside a milestone are fine; push at least once per milestone. For cloud milestones (M4.4, M4.5, M4.6, M5.1, M8.1), also add one line saying where to switch the feature on and which key it needs, so the owner can test it live later.
5. Never push a failing suite. If a milestone cannot be finished without the owner, leave it unticked with a one-line reason in the pull request and continue with the next milestone that does not depend on it.
6. Update `docs/quality/IMPLEMENTATION_STATUS.md` in the last milestone of each phase.

**No GitHub Actions.** Both workflows in `.github/workflows/` run on any push to `main` (Pages deploy), and `release-macos.yml` also builds and publishes a DMG when `native_macos/branding/**` changes, which M1.3 touches. Neither runs on branch pushes or pull requests today. Therefore:

- Never push to `main`, never merge or mark the pull request ready, never enable auto-merge.
- Never run `gh workflow run`, `gh run rerun` or anything else that dispatches a workflow.
- Never create tags or GitHub releases, and never edit `.github/workflows/`.
- If a workflow ever gains a `pull_request` or branch trigger, stop opening or updating pull requests and only push the branch.
- Add one line to the pull request description: "Merging into main runs the Pages deploy, and the macOS release workflow because M1.3 changes native_macos/branding."

## Where things stand (measured, from docs/quality)

| Fact | Value |
|---|---|
| Local end-of-speech → translated row | 5.1 – 7.5 s on single clips, 10.3 s p95 in a three-row replay; 4 s target not met |
| whisper-small on 30 public Saudi-English clips | WER 65.8%, English terms recalled 4.3% |
| Code-switch medium model, same clips | WER 54.3%, terms 60.2%, RTF about 1.0 (cannot keep up live) |
| large-v3-turbo on this CPU | RTF 1.07 (too slow) |
| Opus-MT term protection | lost a protected English term in 13 of 30 lines |
| Paid providers | none registered; `binding.monthly_cap = 0` is hard-coded in `engines/registry.py` |
| App icon | `installer/Translito.ico`: 7 sizes, every pixel alpha 255, corners (0,0,0); PNG masters are RGB with 84% near-black pixels |

Conclusion: recognition is the bottleneck, and no local model on this CPU fixes it. The path is a streaming cloud engine behind a local cost gate, with the local pipeline kept as the free fallback.

## Milestones

Work in this order. Each row is one commit-and-push (see Git above) and one checklist item in the pull request.

| ID | Scope | Done when |
|---|---|---|
| M0 | Commit this handover and `branding/`; open the draft pull request | Pushed |
| M1.1 | `tools/build_icons.py` and generated Windows/web assets | Tests check sizes and transparent corners of every .ico frame and tray PNG |
| M1.2 | Icon wiring in `gui.py`: `iconphoto`, AppUserModelID, tray state images | Tray image swaps on state change in a test with a fake tray |
| M1.3 | macOS icon PNG, `.icns` and `AppIcon.appiconset` regenerated | Files regenerated; transparent margins checked in a test |
| M2.1 | Settings helper: every control saves on change and restores on launch | Round-trip test for every existing control |
| M2.2 | Settings window: sidebar and pages, existing controls moved, no behaviour change | Existing settings tests pass against the new layout |
| M2.3 | Languages page: one pair picker, English pass-through checkbox, variety | Mapping to `Conversation` / one-way pair tested for all cases in P2 |
| M2.4 | Main window: status bar wording, translation-first rows, subtitles switch placeholder | Row and status tests updated |
| M3.1 | Delay measurement per line, rolling median, p50/p95 in the ledger | Tests with a fake clock |
| M3.2 | Engine-dependent assembler wait, provisional text, re-translate merged lines | Pipeline tests with fake ASR/MT |
| M3.3 | Two-beam Fast preset for local translation | Config and adapter tests |
| M4.1 | Capability registry, model lists, default provider/model with per-pair overrides | Router order and resolution tests |
| M4.2 | Monthly budget wired end to end; remove forced `monthly_cap = 0` | Ledger tests: $0 blocks every paid reservation; cap and fallback switch |
| M4.3 | Cost guard: session control by `billing_mode`, ledger `captured/sent` seconds | Silence and music replay through a fake streaming provider opens no stream and bills $0 |
| M4.4 | Soniox one-stream interpreter (pair-agnostic) | Mock WebSocket contract tests |
| M4.5 | Streaming recognizer protocol, ElevenLabs and Speechmatics adapters, paid Gemini rate | Mock transport tests, including token usage settlement |
| M4.6 | Engine page, Cost & usage page, Connect dialog, status bar cost and delay | UI state tests in preview mode |
| M5.1 | Check runner moved into the app (fake providers plus cached local engines) | Scores, delay and cost computed on fixtures |
| M5.2 | Check dialog and `checks.json` | Results saved per pair, engine and machine |
| M6.1 | Subtitle overlay window | Window styles applied through a mocked Win32 layer |
| M6.2 | Overlay controls, four entry points, per-monitor position | One shared state, persisted; tests for each entry point |
| M7.1 | Default meeting app | Resolution by executable name with fake process lists |
| M7.2 | Schedule: iCal and weekly times, auto start and stop, toast | Fixture `.ics` with recurrence and time zones and a fake clock start and stop a session; "wait for app audio" with a silent fake app starts nothing |
| M8.1 | Reply suggestions: generation, strip, phrasebook fallback | Mock translator JSON; romanization rules |
| M8.2 | Reply hotkeys (recordable) and the tray under the subtitle bar | Hotkey registration and overlay tray tests |

---

## P1. App icon

Problem: the icon is an opaque black square with the glyph at about two thirds of the canvas, so Windows shows a black tile in the title bar, taskbar and tray.

Fix: the bubble itself is the icon. Transparent outside the bubble, glyph filling the canvas. White ring, near-black interior, white bars: the ring reads on a dark taskbar, the black bubble reads on a light one. Figma frame `11 App icon`.

- Masters: `branding/translito-mark.svg` (regular cut, 48 px and up) and `branding/translito-mark-small.svg` (bold cut for 16 – 40 px). Geometry on a 400 box: bubble path `M227 345A163 163 0 1 0 157 341V382Z`, ring stroke 26 (bold cut 38, tail to 376), bars 28 wide at x 126/186/246 (bold cut 42 wide at 119/179/239).
- Add `tools/build_icons.py` (Pillow, 4× supersampled, no new runtime dependency) that writes:
  - `installer/Translito.ico` with 16, 20, 24, 32, 40, 48, 64, 128, 256 px, 32-bit RGBA, real alpha.
  - `engines/data/tray/` PNGs at 32 and 64 px for idle, listening (green dot), paused or budget reached (orange dot). `setup_tray` currently opens the .ico and converts it; pass these instead and swap on state change.
  - `website/static/translito-icon.png` (512, transparent) and replace `website/static/favicon.svg`, which is an unrelated blue glyph today.
  - macOS: `native_macos/branding/Translito-AppIcon-1024.png` as a dark rounded tile at 824 of 1024 px with transparent margins, then regenerate `Translito.icns` and the `AppIcon.appiconset`. On macOS 26 a non-conforming square is shrunk into a grey box, so the native build should move to a layered Icon Composer asset later; note it in `native_macos/README.md`, do not block on it.
- `gui.py`: keep `iconbitmap(default=...)`, add `iconphoto(True, ...)` with 32/64 px PNGs, and set an explicit AppUserModelID before creating the root window so source runs group under the app icon.
- Tests: every .ico frame and tray PNG has the listed size, transparent corners and a non-empty glyph; the website icon is transparent; `setup_tray` loads the state images.

## P2. Settings shell, Languages page, persistence

Replace the single 520×560 scrolling window (11 cards, 5 extra dialogs) with an 820×680 window: sidebar on the left, one page at a time on the right. Figma frames 03 – 07 and 12.

Sidebar: **Translation** (Languages, Engine, Cost & usage) · **On screen** (Subtitles, Schedule) · **System** (Audio, Models, General).

Old → new mapping:

| Today | Goes to |
|---|---|
| General → Open at login | General |
| Hotkeys | General (add "Show or hide subtitles" `ctrl+alt+u`, "Suggest replies" `ctrl+alt+r`, "Say reply 1/2/3" `ctrl+alt+1/2/3`; all recordable) |
| Bilingual conversation, Advanced one-way pair | Languages (one pair picker) |
| Edit terms | Languages → Your terms |
| Speech Recognition: Saudi Arabic setup, speed check, quality, model ID, legacy window | Engine → Advanced, and Models; "Check this PC's speed" becomes the Speed and accuracy check |
| Offline mode | Engine: "On this PC" is the offline choice; "never download" stays in Models |
| Translation engine profile, Cloud providers and usage | Engine (three choices) and Cost & usage; the seven-tab notebook becomes the Connect dialog (frame 09) |
| Local translation → TranslateGemma | Models |
| Capture → mic noise gate | Audio |
| Speak Mode → voice, monitor; "When I speak…" | Audio → Speak mode |
| Transcripts folder | General |
| Manage models | Models (existing `model_library_ui.py`) |

Languages page logic (UI change only; the engine model stays):

- "Spoken language → Translate to" plus the checkbox "Speakers also use English. Show it as spoken, do not translate."
- Spoken X, target English, box ticked → existing `Conversation(other_language=X, my_language="en")`.
- Box clear, or neither side is English → existing one-way pair.
- Spoken English, target X → `Conversation(other_language=X, my_language=X)`.
- New optional `variety` (for example `ar-SA`): passed as a recognizer language hint where the provider accepts one, named in the translation prompt, and used to pick the check sample.

**Persistence (item 8).** Every control saves the moment it changes and is restored on launch. No Save button anywhere. This covers the main window too: mode, pair, source, subtitles on screen, reply strip shown or hidden, window size and position; and the overlay: position per monitor, text size, lines. Add one small settings helper so each control is a single line (`bind(var, section, key, default)`), rather than extending the long `persist_settings`. Test: change each control, restart with the same config, assert the state.

Tk notes: a switch is a small Canvas widget (same approach as the existing `MacScale`); radio cards are Frames with `highlightbackground`; keep `ScrollableFrame` inside each page for short windows. Color tokens in Figma are named after `COLORS` keys; four are new: `blue_bg #16293f`, `on_accent #ffffff`, `black #000000`, `desktop #0f1114` (mock background only). Inter stands in for Segoe UI in Figma. No italics.

Wording changes to keep: "Listen" / "Speak" for the modes; "Delay", "Engine", "Session", "This month" in the status bar instead of "ASR: Local · MT: Local"; the translation is the primary line in each row and the original sits under it, right-aligned and quieter (today it is the reverse).

## P3. Delay measurement and free latency fixes

- Per line record `speech_end_at` (already derived from `captured_at - endpoint_delay_s`), `source_shown_at`, `target_shown_at`; store `delay_s` on the entry. Show it in the row meta and a rolling median in the status bar. Write p50/p95 per session into the usage ledger so the Engine page can show a measured figure.
- `SentenceAssembler(idle_seconds=1.5)` costs up to 1.5 s on every unpunctuated line. Make the wait engine-dependent: 0 when the provider signals its own endpoint, about 0.5 s for local. If the next segment continues the sentence, re-translate the merged text and update the row (`transcript_update` already supports it).
- Show provisional source text immediately in a quieter color and replace it on final. For streaming engines re-translate only when the committed source grows by 4 – 6 words or a boundary arrives, and hold back the last 2 – 3 target words on provisional lines to limit flicker.
- Local Opus path: offer 2 beams instead of 4 in the Fast preset. Do not reopen the marker-format experiments; term preservation is solved on the cloud path by the LLM prompt that already exists in `mt_gemini.py`.

## P4. Paid streaming engines, budget, cost guard

### Engines to add

Promote the evaluation contracts in `tools/eval/streaming_protocols.py` and the transport in `streaming_runner.stream_clip` into `engines/` as production providers. Two shapes:

1. **One stream does both** (Soniox real-time with translation). Implement the existing `StreamingInterpreter` protocol in `engines/types.py`, the way `interp_gemini_live.py` does, and run it through `LiveConversationPipeline`, which already handles source/target events, row updates and fallback.
2. **Streaming recognizer plus translator** (ElevenLabs Scribe live, Speechmatics Melia, then an LLM). Add a `StreamingRecognizer` protocol (partial and final source text, language, timings) and translate finals through `TranslatorRouter` with a paid `gemini` binding.

Required changes:

- `SonioxProtocol` raises unless the pair is Arabic/English. Remove that; drive language hints and the translation target from the selected pair. Update the model ID (the eval file pins `stt-rt-v5`, reported as scheduled for removal on 15 Dec 2026; `stt-rt-v6` was released 3 Nov 2026). `ElevenLabsProtocol` pins `scribe_v2_realtime`; the current live model is Scribe v3 Live with a mid-sentence language-switch mode and a keyterm library that the SDKs do not expose yet, so stay on the raw WebSocket. Confirm exact IDs and parameters in the provider docs.
- `engines/mt_gemini.py`: `build()` returns `rate=None` for anything but a consenting free account, which makes the router raise "pricing policy is not configured". Add a paid rate (`per_million_input_tokens`, `per_million_output_tokens`), disable thinking, and use the streaming endpoint so the first words arrive early.
- `engines/registry.py`: stop forcing `binding.monthly_cap = 0`; use the provider cap and the user's monthly budget. Extend `ProviderFactory` with the capability fields in section 9.
- Engine choice replaces the profile names in the UI. Internally: Cloud, pay as you go → `custom` with paid bindings first; On this PC → `offline`; Free cloud allowances → `free`. Gemini Live preview becomes one more provider in the list rather than a profile (it is still a preview and priced far above the others).

### Default provider and model (item 9)

The Engine page (frame 04) has a "Default provider and model" block. There is no such control today; routing order is fixed in `registry.build_session_routers`.

- Four pickers: Recognition provider, Recognition model, Translation provider, Translation model. Provider lists show connected providers that support the selected pair; model lists come from a `models` list on each provider in the capability registry (id, label, kind, rate, date checked), so a new model is a data change.
- A one-stream provider (Soniox with translation) fills the translation side itself: show "Same stream as recognition" / "Built in" and disable those two pickers.
- "Use these defaults for": All pairs, or only the current pair. Store a global default and optional per-pair overrides; resolve per pair first, then global.
- The router puts the default first and keeps the others as fallback in the order set under Advanced. Changing the default never removes a fallback.
- The Connect dialog (frame 09) has "Make this my default provider", ticked for the first provider connected.
- The same idea for the local path: "Default local model" under Advanced and on the Models page replaces the raw Model ID field. `LanguageConfig.whisper_model` already stores it.
- "Manage keys" opens the Connect dialog list. A default whose key is missing or untested shows as "needs a key" and the session falls back, with a visible notice.

### Monthly budget in the UI (item 10)

The keys already exist and are read by `engines/settings.py`: `[ENGINES] monthly_cap_usd` and `<provider>_monthly_cap_usd`. Nothing in the UI writes them and the router is forced to 0. Expose them:

- Cost & usage → Monthly budget (frame 05): amount, what happens when it is reached, warn-at percentage. This is the primary place.
- Engine page (frame 04): the same amount inline next to the paid choice, so it is set where "pay as you go" is chosen. Both fields edit one value.
- Connect dialog (frame 09): optional per-provider limit.
- Main window: "This month $x of $y" in the status bar opens Cost & usage.
- Choosing "Cloud, pay as you go" while the budget is $0 asks for a budget before anything is sent. A blank or invalid amount is treated as $0 (`budget()` already validates).
- Changes apply to the running session at the next reservation; lowering the budget below the amount already spent switches to the fallback immediately.

### Rates and billing (list prices checked 25 Nov 2026; verify)

| Provider | List price | How it bills | Evidence for Saudi Arabic + English |
|---|---|---|---|
| Soniox real-time, with translation | $2/M audio tokens, $4/M text tokens; about $0.18 per hour with translation, $0.12 without | **Whole time the stream is open**, including pauses and keepalives | Vendor claims only |
| ElevenLabs Scribe v3 Live | $0.22 per hour (keyterm surcharge unverified) | Every second of audio sent, **silence included**, no minimum | Scribe v2 ranked first on the Perle Saudi code-switch benchmark (13.2% mean WER overall vs 38.6 – 43.6% for OpenAI, Google, Azure) |
| Speechmatics Melia 1 real-time | $0.40 per hour undiscounted ($0.20 is shown with opt-in discounts); $100 trial credit | Per second; whether a quiet open session bills is not stated | Strong on Saudi broadcast speech; no code-switch result |
| Gemini 3.1 Flash-Lite (translation) | $0.25/M input, $1.50/M output; about $0.09 per hour of Arabic speech with a 600-token prefix per request | Tokens | LLMs beat classic NMT on Saudi dialect in the Alexandria benchmark |
| Groq whisper-large-v3 (existing adapter) | $0.111 per hour | **10 s minimum per request**; 3 – 4 s utterances cost roughly 2.5 – 3× | Weak on Saudi; not for live |

Sources: soniox.com/pricing, elevenlabs.io/pricing/api, speechmatics.com/pricing, ai.google.dev/gemini-api/docs/pricing, console.groq.com/docs/speech-to-text, arxiv.org/abs/2605.19069, arxiv.org/abs/2601.13099.

Worked cost, per meeting hour, gated audio = speech share × 1.15:

| Stack | 100% Arabic | 50% | 25% | 20 h a month at 50% |
|---|---|---|---|---|
| Soniox one stream | $0.21 | $0.10 | $0.05 | about $2 |
| Scribe live + Flash-Lite | $0.34 | $0.17 | $0.09 | about $3.40 |
| Melia + Flash-Lite | $0.55 | $0.28 | $0.14 | about $5.50 |

### Cost guard ("pay only for real speech in my languages")

The hourly rates are small; what moves the bill is paying for silence, open connections and per-request minimums. So the guard controls sessions, not only frames.

1. Silero VAD (keep). Consider onset 0.5 with 0.25 release hysteresis and at least 250 ms of speech to open; today it opens at 0.35.
2. Reject non-speech: use the `no_speech_prob` from the pair language-ID pass that already runs; add a tiny audio-event check for music and typing only if the replay test shows it is needed.
3. Pair language ID (existing faster-whisper base detector, generalized from Arabic vs English to the selected pair). With engines that handle mixed speech it decides only whether to translate; English lines pass through free. Speech in any other language is not sent.
4. Session control by a new `billing_mode` on each provider:
   - `open_stream` (Soniox; assume Speechmatics until an invoice shows otherwise): open on gate-open, finalize after about 0.8 s of silence, **close after 8 – 10 s without gated speech**. Never idle on keepalive. Keep a 1 s local pre-roll so the reconnect is not heard.
   - `audio_sent` (ElevenLabs): send only gated audio plus about 300 ms padding; never stream silence to hold the socket; reconnect with the pre-roll.
   - `per_request_min` (Groq): merge segments to the minimum or do not use for live.
5. Reserve before sending, in blocks, as `interp_gemini_live.py` already does; hard-cap a single session's length.
6. Ledger additions: `captured_seconds`, `sent_seconds`, `translated_chars` per session, so the UI can say "14 of 32 min sent" and estimate what the guard saved.
7. Budget: monthly amount, warn at a chosen percentage, and on reaching it either continue on this PC (router fallback on `BudgetExceeded` already exists; make the switch visible) or stop.

### Cost and delay in the UI

- Status bar (frame 01): Delay · Engine · Session cost and minutes sent of minutes captured · Month to date of budget.
- Transcript: a quiet divider for gaps ("2 min 40 s without speech · nothing sent"); English lines marked "shown as spoken, not sent".
- Idle state (frame 02): states the measured local delay and the cloud alternative for the current pair, with "Compare engines".
- Engine page (frame 04): three choices, each with Delay, Accuracy, Cost. Every figure is labelled measured, estimate or not measured. Nothing unmeasured is shown as a number without that label. Below them: default provider and model, monthly budget, fallback, scope.
- Cost & usage page (frame 05): month, speech sent of captured, average per meeting hour, budget, the three guard switches, per-provider totals.
- Connect dialog (frame 09): provider, key, Test on the bundled public clip, per-provider limit, what the provider receives.

## P5. Speed and accuracy check

Turn `tools/eval` into an in-app dialog (frame 10) that runs the same clips through each connected engine and fills the Engine page.

- Samples per pair in `tools/eval/sets/`: Arabic → English uses the public Perle Saudi set already pinned (30 clips; allow the full 300). Other pairs use a small public sample for the source language with reference text (FLEURS is parallel across languages), or the user's own recording, in which case accuracy is blank and only delay, cost and side-by-side output are shown.
- Columns: delay p50/p95 (speech end → final translation, replayed in real time through the real gate), accuracy shown as words right (100 − WER, with Arabic normalization for hamza, ta marbuta and digits), English terms kept, cost per hour of speech.
- Show the estimated cost before running and take it from the budget; the Arabic sample costs cents per cloud engine.
- Save results per pair, engine and machine in `%LOCALAPPDATA%\Translito\checks.json` with the date.
- Recommendation rule: the cheapest engine within about 3 WER points of the best, with at least 80% English-term recall and p95 delay at or under 2.5 s. Recommend; let the user choose.
- Codex builds and tests the check with fake providers, and may run the on-PC rows only if those models are already cached. Running it against real cloud providers is left to the owner (section 13).

## P6. Subtitles on screen

A borderless, always-on-top bar that shows translations over any window, including when the main window is minimized or hidden to the tray. Figma frames 06 and 08.

- `tk.Toplevel` with `overrideredirect(True)`, `-topmost`, alpha background. On Windows add `WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE` and, when click-through is on, `WS_EX_TRANSPARENT`; lift click-through while the pointer is inside the bar so the hover controls work (poll the cursor). Round the corners with a window region.
- Content: 1 – 3 lines, previous line quieter, current line large, provisional text quieter; optional original line (reuse `engines/display.py` for Arabic shaping and bidi).
- Hover controls: pause, text smaller, text larger, move, open app, hide. Dragging saves the position for that monitor.
- Show: whenever listening, or only while the main window is minimized. Screen: the monitor holding the default meeting app's window, else the primary. Fades after a chosen time without speech.
- Entry points: switch in the main window, tray menu item, hotkey `ctrl+alt+u`, Settings → Subtitles. All four reflect and persist the same state.
- Worth adding (not drawn): "Hide subtitles from screen sharing" using `SetWindowDisplayAffinity`, so a shared screen does not show them.
- The native macOS app is out of scope here; note the equivalent (non-activating floating panel) in `native_macos/README.md`.

## P7. Default meeting app and Schedule

**Default meeting app** (frame 12, Audio page). Most people use one app.

- Persist the executable name (not the PID), chosen from `process_audio.active_sources()`, and ask once on first run.
- On Start, resolve the running app root by name. If it is not open: wait for it (poll) or listen to everything playing, per the setting. The main window shows "Zoom · your meeting app".
- Browser meetings capture the whole browser's audio; say so in the picker.

**Schedule** (frame 07).

- Sources: a read-only iCal link (Google, Outlook, iCloud) or fixed weekly times. Treat the link as a secret: store it in Credential Manager, never in `config.ini` or logs. Fetch with the existing HTTP client, refresh every 15 minutes, tolerate being offline. Recurring events and time zones need a real parser; pin a small pure-Python iCalendar library rather than hand-rolling RRULE.
- Start a chosen lead time before the meeting; stop at the end or after a chosen time without speech.
- "Wait until the meeting app plays audio" arms the session and starts only when the default app has an active audio session, so a no-show costs nothing.
- A toast announces each automatic start with Stop and Settings. Never auto-start Speak mode. Do not start if a session is running. Scheduled sessions obey the budget.
- Needs the app running in the tray; point to "Open at login" when the schedule is enabled.

## P8. Reply suggestions

After a line in the other language, offer up to three short replies **in that language, written in English letters, each with its meaning** (frame 13). Example for "When can we deliver the first version to the client?": "Nihayat al-usbu, inshallah" — By the end of the week, God willing.

- Trigger: automatically when the line is a question, or by shortcut. "More" regenerates. Hide state is remembered.
- **Shortcuts are mappable.** Add four actions to `DEFAULT_HOTKEYS` / `HOTKEY_LABELS`, recordable in General → Hotkeys exactly like the existing ones: `replies` "Suggest replies" (default `ctrl+alt+r`) and `reply_1`, `reply_2`, `reply_3` "Say reply 1/2/3" (default `ctrl+alt+1/2/3`). Saying a reply sends its `native` text through Speak mode; if no Speak output is configured, the shortcut copies the romanized text to the clipboard and says so in the strip. The strip shows the current bindings and a number on each card. The shortcuts work while the main window is minimized, and act on the set currently shown (main window or subtitle bar).
- One call to the translation model with the last 2 – 3 lines as context. Ask for JSON: `replies: [{native, romanized, meaning}]`, at most 8 words each, neutral polite register, matching the selected variety, always including one "please repeat" option. Romanization is plain ASCII an English speaker can read aloud, no diacritics. For Latin-script languages skip `romanized` and show the phrase.
- Cost is a few hundred tokens per set (well under a tenth of a cent on Flash-Lite); generate only when there is somewhere visible to show them (the strip or the subtitle tray) and count it in the ledger.
- The speaker button says the `native` text through Speak mode's output when one is configured.
- Without a cloud translator, fall back to a small bundled phrasebook per language (yes, no, one moment, please repeat, thank you) or hide the strip.
- **On the subtitle bar too.** When subtitles are on screen and reply suggestions are on, the same set shows in a tray under the subtitle bar (frame 14), so it is visible with the app minimized: number, romanized reply, meaning. On by default (`show_on_overlay = 1`); it can be turned off on the Languages page. The tray follows the bar's position and text size, leaves when the next line arrives or after the fade time, and is click-through like the bar. The say-reply shortcuts act on whichever set is showing.
- Options (Languages page): on/off, when to suggest, show the native script as well, show on the subtitle bar.

---

## 9. Engine capability registry (what makes it pair-agnostic)

Extend `ProviderFactory` (or add a sibling table) with: `source_languages`, `mixed_speech` (can it switch language inside a sentence), `translates_to` (for one-stream engines), `streaming`, `billing_mode`, `rate` and `rate_checked_on`, `min_billed_seconds`, `data_note`, `setup_url`. The Engine page, Connect dialog, cost estimates and the check all read from it for the selected pair. An engine that does not support the pair is listed as unavailable with the reason, not hidden. No language name appears in control flow; "Set up Saudi Arabic recognition" becomes "Recommended local model for <language>" on the Models page.

## 10. New config keys (additive)

```
[UI]         subtitles_enabled, reply_strip_visible, window_geometry, last_settings_page
[LANGUAGE]   variety
[ENGINES]    engine_choice (cloud | local | free), fallback_on_budget (local | stop),
             budget_warn_percent, <provider>_billing_mode_verified,
             default_asr_provider, default_asr_model, default_mt_provider, default_mt_model,
             pair_<src>_<tgt>_asr_provider / _asr_model / _mt_provider / _mt_model (optional overrides)
             (existing, now written by the UI: monthly_cap_usd, <provider>_monthly_cap_usd)
[COSTGUARD]  skip_non_speech, skip_other_languages, close_idle_seconds
[SUBTITLES]  show_when (listening | minimized), position_<monitor>, lines, text_size,
             background_alpha, show_original, click_through, fade_seconds, hide_from_capture
[SCHEDULE]   enabled, source (ical | weekly), weekly_times, lead_seconds, stop_rule,
             wait_for_app_audio, ask_before_start, only_with_call_link
[CAPTURE]    default_app, if_app_closed (wait | everything)
[REPLIES]    enabled, trigger (question | hotkey), show_native, show_on_overlay
[HOTKEYS]    subtitles = ctrl+alt+u, replies = ctrl+alt+r,
             reply_1 = ctrl+alt+1, reply_2 = ctrl+alt+2, reply_3 = ctrl+alt+3
```

## 11. Figma frame map

Page "Translito v2 · UX" (page id `10:2`). Append `?node-id=<id with a dash>` to the file URL.

| Frame | Node | Builds |
|---|---|---|
| Foundations (tokens, type, components) | 10:41 | `COLORS`, fonts, shared widgets |
| 01 Main · Listening | 12:7 | `build_ui`, status bar, transcript rows |
| 02 Main · Ready | 12:141 | empty state, next-meeting indicator |
| 13 Main · Reply suggestions | 16:636 | P8 |
| 08 Desktop · Subtitles while minimized | 14:228 | P6, P7 toast, tray states |
| 14 Desktop · Subtitles with reply suggestions | 20:598 | P6 + P8: reply tray under the subtitle bar |
| 03 Settings · Languages | 13:76 | P2, P8 options |
| 04 Settings · Engine | 15:355 | P4 |
| 05 Settings · Cost & usage | 15:497 | P4 |
| 06 Settings · Subtitles | 13:194 | P6 |
| 07 Settings · Schedule | 13:315 | P7 |
| 12 Settings · Audio | 16:507 | P7 default app, capture, Speak mode |
| 09 Dialog · Connect a cloud provider | 15:623 | P4 |
| 10 Dialog · Speed and accuracy check | 15:682 | P5 |
| 11 App icon | 14:306 | P1 |

Models and General are not drawn: they hold existing controls unchanged (see the mapping in P2). Figures in the mocks: on-PC values are the real measurements; cloud delay is an estimate and cloud accuracy is deliberately blank until the check runs; month and session amounts are sample data at $0.18 per hour.

## 12. Done means (automated tests only)

All of these are checked by `python -m pytest -q`, using fakes, mocks, fixtures and synthetic audio. Benchmark pair Arabic → English; the "any pair" item proves it is not Arabic-only.

- **Delay:** each line carries `delay_s`; p50/p95 are computed and stored; the assembler adds no wait when the engine signals its own endpoint (fake clock).
- **Cost guard:** two hours of synthetic silence or music on the source open no stream and reserve $0. A synthetic meeting with long pauses reserves no more than speech time × 1.25 against a fake `open_stream` provider and a fake `audio_sent` provider.
- **Budget:** settable from Cost & usage and the Engine page, both editing one value. With $0 no paid reservation succeeds. At the cap the session falls back or stops, as configured, with a notice event.
- **Defaults:** the chosen recognition and translation provider and model come first in the router, per pair when an override exists, and survive a restart. A default without a tested key falls back with a notice.
- **Any pair:** Spanish → English and English → Arabic pass through Languages, the router, the check, the overlay and reply suggestions with fake providers and no code change.
- **Persistence:** every control listed in P2 round-trips through a restart with the same config.
- **Subtitles:** the overlay requests the expected window styles through a mocked Win32 layer; all four entry points share one persisted state; per-monitor position round-trips.
- **Schedule:** a fixture `.ics` (recurrence, time zones) starts and stops a session on a fake clock; with "wait for app audio" and a silent fake app, nothing starts and nothing is reserved.
- **Replies:** suggestions parse from mock JSON, romanization is ASCII, hotkeys are recordable, and the overlay tray shows the same set.
- **Icon:** every .ico frame and tray PNG has transparent corners and the listed sizes.
- Suite stays green at every pushed milestone.

## 13. Left for the owner (not for Codex)

Codex does not do, schedule, ask about or wait for any of these. They are listed only so they are not attempted.

- Testing every cloud feature live with real keys. No API keys will be provided to Codex.
- Approving any spend, setting a real budget, creating provider accounts or keys, and checking card billing from Bangladesh.
- Running the speed and accuracy check against real cloud providers, comparing the ledger with invoices, and any recorded-meeting replay.
- Looking at the app on screen: icon on the taskbar, overlay over a real meeting, toasts, layouts.
- Anything with physical audio devices, VB-CABLE, installers, reboots or the installed app.
- Connecting a real calendar link.
- Trying new local models that need downloads or licence acceptance (Arabic-first models such as Audar-ASR and Jais-ASR, whisper.cpp on the integrated GPU).
- Merging the pull request, which also runs the Pages and macOS release workflows.

## 14. Pitfalls

- Do not push to `main`, merge, tag, release or dispatch a workflow. Pushes to `main` and dispatches start GitHub Actions; tags and releases are the owner's call.
- Do not push a milestone with a failing suite, and do not let a milestone pass without pushing it.
- Do not leave a Soniox-style stream open in keepalive; that is billed time. This is the single most likely way to overspend.
- Do not stream silence to keep an ElevenLabs session alive.
- Do not treat the list prices or model IDs here as verified constants.
- Do not show an unmeasured number without its "estimate" label.
- Do not put the calendar link or any key in `config.ini`, logs or reports.
- Do not auto-start Speak mode from the schedule.
- Do not hard-code Arabic anywhere new; the eval contracts currently do.
- Vendor accuracy claims (Soniox Arabic WER, Scribe v3 gains) are marketing until the check measures them. The only independent Saudi code-switch comparison used scripted speech and the previous Scribe version.
