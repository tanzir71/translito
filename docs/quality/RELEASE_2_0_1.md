# Windows 2.0.1

Updated 26 November 2026. This is the implementation of
`CODEX_HANDOFF_V2_1_FIXES.md` and `CODEX_HANDOFF_V2_1_ADDENDUM_ICON_SCHEDULE.md`.
The Windows installer and portable package are version 2.0.1. Packaging evidence and artifact hashes are recorded below.

## The five reported problems

| Report | Result | Automated coverage |
| --- | --- | --- |
| Model preload fails on a partial Whisper snapshot | Readiness checks distinguish missing, incomplete, corrupt and ready models before construction. Loading uses local files only. An incomplete preferred model falls back to ready Turbo, Small or Base; the yellow hint offers Resume, Repair or Download. Cloud startup does not preload weights. | `tests/test_model_files.py`: partial snapshot, manifest verification, fallback order and cloud startup; `tests/test_model_library.py` and `tests/test_model_library_ui.py`. |
| TranslateGemma download has no progress and blocks the app | A lower-priority child process downloads, hashes, verifies the chat template and performs the first load. Byte progress is shared by the dialog, app and tray. Downloads queue, pause, resume or cancel; saved jobs survive restart. Existing Hugging Face blob downloads resume in their cache. Stalls retry three times. Sessions and settings remain available. Later Gemma loads are lazy and leave one physical core free. | `tests/test_downloads.py`: real fake-fetcher child with incremental bytes, pause/resume/cancel/queue, checksum failure, disk space, stalls, frozen stdout pipe and a five-second Tk heartbeat; Gemma adapter tests. |
| Selected tab hover becomes white | Every used ttk style has explicit dark hover, pressed, selected, disabled and focus states. Sidebar hover and selection are dark. | `tests/test_v2_ui.py`: styles collected from source, state colors, focus and contrast checks. |
| Settings seem unsaved | One store owns each config path. Typed canonical bindings replace duplicate UI keys, validate money, coalesce text writes and preserve comments/unknown settings. Writes retry locked files and show Saved, Retry or an error. Stale worker snapshots cannot undo newer UI choices. Device display labels map to runtime device names; temporary missing-device/voice fallbacks do not replace saved choices. | `tests/test_settings_store.py`, `tests/test_settings_state.py`, and the writes-enabled real `TranslatorGUI` harness in `tests/test_settings_ui.py`: restart/runtime values, Speak devices/voice, migration, invalid money, save feedback, concurrency and weekly schedule. |
| Cloud setup is confusing and asks for a comparison check | Settings > Engine contains the three engine choices and an inline provider, masked key, Connect, budget and connection status. Connect uses authenticated metadata endpoints without audio; Azure's documented exception sends one character of text. Advanced retains provider/model/limit/consent options. The status bar and transcript explain actual fallback. Comparison tools live only under Models > Tools. | `tests/test_cloud_connect.py`, `tests/test_settings_ui.py`, `tests/test_paid_streaming.py`, `tests/test_live_pipeline.py` and existing cost-guard/router tests. All HTTP and credentials are fake. |

The monthly budget still blocks every paid request at $0. Local speech and
language gates still run before paid audio opens. A ready local speech model is
therefore needed for that gate even when the selected audio engine is cloud.
Choosing On this PC permits explicit model downloads; the separate Block internet
setting controls network privacy. No code sets Hugging Face's process-wide
offline environment flags.

Connect checks use Soniox models, Speechmatics EU jobs metadata, ElevenLabs user,
Gemini/Groq/Cohere models, DeepL usage and Google Translation languages. Keys stay
in Credential Manager; connection signatures contain provider and key only.
Last-four key labels are derived in memory. An empty per-provider cap inherits
the shared monthly budget. Rejected key and connection failures are sanitized.

List prices were checked on 26 November 2026: Soniox's displayed estimate is
$0.18/hour, ElevenLabs Scribe Live $0.22/hour and Speechmatics Melia realtime
$0.40/hour before discounts. Actual token-priced usage remains ledger-based.
Sources: [Soniox](https://soniox.com/pricing),
[ElevenLabs](https://elevenlabs.io/pricing/api),
[Speechmatics](https://www.speechmatics.com/pricing.md).

## Icons, workdays and display scaling

App and tray ICOs now contain the exact requested sizes, generated once from
4x artwork with the small cut through 40 pixels. Native window and tray handles
use the current DPI's icon metrics. Main, settings and dialogs share the app
icon, and the installer shortcuts share `Translito.Desktop.v2` from one constant.
`tests/test_icons.py` checks frame contents, mocked Windows calls, the pinned
pystray override, fallback behavior and shortcut identity.

Build the comparison sheet with `python tools/build_icons.py --sheet`:
[old/new tray and taskbar contact sheet](icons-2.0.1.png).

Schedule supports grouped workdays, Every day / Mon–Fri / Sun–Thu presets,
editable 15-minute times, overnight ranges, per-block zones, different hours and
three upcoming occurrences with individual skips. Migration groups old rows;
default UTC clocks become PC-local clocks with a one-time notice. Explicit zones
are preserved. Open at login uses `--tray` and starts quietly. Downloads do not
block scheduled starts. `tests/test_workday_schedule.py` covers migration,
summaries, ordering, overlap, DST, skips and startup; the real desktop harness
covers editing, validation and restart. Frozen runtime probes include tzlocal
and Asia/Dhaka zone data.

F9 is isolated in commit `e257a4d` so system-DPI awareness and scaled layout can
be reverted separately. Source and frozen startup use system awareness. Fixed
pixel layout values scale with DPI while font sizes remain in points; saved
geometry records its DPI. `TRANSLITO_UI_SCALE` is available for tests.
`tests/test_ui_scale.py` checks the manifest, awareness ordering, source literals,
geometry migration and a real 1230x1020 settings window at 150%, including every
settings page and the download, provider and comparison dialogs.

## Verification and owner checks

The standalone fix branch passed 587 tests. After merging the fixes into
`codex/v3-languages-landing`, the combined full suite passed 803 tests, including
the real Hugo site builds. The same resolved integration is carried on
`codex/v2.1-fixes` for PR review. Both runs reported only the existing Torch
deprecation warning.

Run the full suite with `python -m pytest -q`. Tests forbid external connections
and real Credential Manager access. Fake model fetchers write only to temporary
folders. No model weights, recordings, real calendar or API keys are required.
Automated checks do not establish live cloud quality, latency, real download
throughput or visual acceptance on the owner's display.

The owner can later connect Soniox and test an Arabic meeting, resume the actual
Whisper Turbo snapshot, download TranslateGemma, inspect the contact sheet and
check tray/taskbar rendering after installing. A Sun–Thu schedule can then be
verified at the next workday start. The Windows packages below retain existing settings, transcripts and cached models. The macOS DMG is the existing 1.0 build, unchanged.


## Packaging verification and artifacts

- Application source: `d3b0632351f5f625680ecc5940bb7333b7d7de70`; the release tag also includes packaging documentation.
- Merged main-source suite: **803 passed**, one existing Torch deprecation warning.
- CPU-only Python 3.13 build: Torch 2.13.0+cpu, Transformers 5.22.1 and PyInstaller 6.22.3.
- The actual frozen EXE passed all **19** dependency checks, including a native CPU tensor calculation, tzlocal and Asia/Dhaka zone data.
- The windowed EXE's download child passed a real inherited-pipe test using a tiny local fake fetcher. It sent byte progress and exited successfully without opening the GUI or accessing models/credentials.
- The portable ZIP passed a complete CRC check. App/tray ICO frames, bundled Tcl/Tk and time-zone files, native audio bridge and every engine data file were verified.
- No owner settings or ASR/translation weights are packaged. The small Silero speech-detection model is intentionally bundled for the local cost gate.
- A real Hugo production build verified the 2.0.1 installer and portable URLs on all 28 pages containing download links.
- No installation, physical audio, live API key or provider inference was used for release verification.

Setup upgrades the app; extract the complete portable ZIP into a new empty folder.
The retained macOS DMG is version 1.0 and does not contain these Windows changes.
[GitHub release v2.0.1](https://github.com/tanzir71/translito/releases/tag/v2.0.1)
includes the runtime report, frozen-child report, dependency snapshot and checksums.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.1.exe | 256,862,688 | `8c41a5b686bbd69a2653d79476cf4b52a656e710b6a19d2839c4db4e49c3eabc` |
| TranslitoPortable-2.0.1.zip | 374,045,388 | `bbb4817de04708c36408480b8ccea3c8ef5470142f7d8e2e41aa7a7f9ae46696` |
| Translito.dmg | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |
| runtime-check.json | 1,458 | `945c91f7048e9f76f55781032bfcd8ac9473362bcfec974b56e4c870f90916e9` |
| frozen-download-check.json | 153 | `b7295b2bd83d54cf3eae24d42e0a31f90c6bbb240012feb2fe2d8481617d5c6f` |
| build-requirements.txt | 2,193 | `64ca9558fc137fd47f622c5c43e879fcc085fb84afef1ef93bcf35eae880939a` |
| SHA256SUMS.txt | 538 | `da73060382a7bc46e9f994140b8775b42c1cdb0e6e4edde4760595de94646bd8` |
