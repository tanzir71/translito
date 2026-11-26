# Codex handover: v2.1 fixes from the owner's 2.0.0 feedback

Repo `tanzir71/translito`, local folder `D:\claude-upgrade-26\translito`. Figma file "Translator" (`qHi2n6YF49UURgSJPYb6tB`), page "Translito v2 · UX", row titled "v2.1 fixes" (frames 15–20).

This is a fix release for the shipped Windows 2.0.0. It comes before the rest of the v3 languages and landing work. Arabic → English is still the benchmark, and every fix applies to every language pair.

## The owner's feedback (26 Nov 2026, Windows 2.0.0)

1. Model preloading fails. Screenshot: red banner "Model preload failed: Unable to open file 'model.bin' in model 'C:\Users\…\.cache\huggingface\hub\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo\snapshots\0a363e9…'", with the hint "Finish the current session or setup first." above it.
2. The TranslateGemma download shows no progress. It should be able to run minimized, in the background, and it freezes the whole app.
3. The hover state on tab switches turns white. Screenshot: the "App audio | Device" switch with the Device half shown as a blank white box.
4. Saving settings feels like nothing is saved.
5. Setting up cloud models should be easy. Instead there is an odd option to run speed and accuracy tests.

## Order of work and git

You are in the middle of v3 (branch `codex/v3-languages-landing`, A1 pushed as `c8df248`, A2 uncommitted in the working tree).

1. Finish A2, run `python -m pytest -q`, then commit and push it to `codex/v3-languages-landing`, as the v3 handover says. Leave nothing uncommitted.
2. Create `codex/v2.1-fixes` from `origin/main` (`74287b9`, the 2.0.0 source plus docs).
3. Work through milestones F0–F6 below. After each milestone, commit with the milestone id in the subject (for example `F2 Check model files before loading and explain missing models`). Run the full suite before each push and never push a failing suite. Push after every milestone.
4. After F0, open one draft PR from `codex/v2.1-fixes` into `main` titled "v2.1 fixes". Its body is the milestone checklist; tick items as they land.
5. After F6, merge `codex/v2.1-fixes` into `codex/v3-languages-landing`, resolve conflicts (expect `gui.py`, `engine_ui.py`, `engines/`), run the suite, push, and continue v3 from A3.

Never push to `main`, merge into `main`, tag, publish a release, run `gh workflow run`, or edit `.github/workflows`. Pushing `codex/*` branches starts no workflow (`hugo.yml` and `release-macos.yml` only run on `main`). Merging the fix branch into the v3 branch is the one merge you are asked to do.

## Ground rules

- Work unattended. Use automated tests only (`python -m pytest -q`). Nothing in this handover needs the owner to click, approve, or test while you work.
- No real API keys, no paid calls, no reads of the real Windows Credential Manager, and no real model downloads in tests. Use fakes: a fake credential store, mocked HTTP, and a fake download fetcher that writes bytes slowly to a temporary folder.
- Cloud features are implemented fully and tested against mocks. The owner tests them live later.
- The v2 safety tests stay green and unchanged in meaning:
  - A $0 budget blocks every paid request.
  - Silence, music and other languages never open a paid stream.
- No italics anywhere in the UI. Follow the Figma frames for layout and copy. Where the code and a frame disagree, the frame wins unless this handover says otherwise.

## What the audit found

Audited `main` at `74287b9`; line numbers refer to that commit. Each section names the cause and the file.

### 1. Model preload fails

- **Every start preloads a local model.** It loads local Whisper on every launch, even when the engine is Cloud (`gui.py:526-532`, `preload_current_models` at `gui.py:2557-2595`). For the owner's settings that is Whisper Turbo, 1.62 GB.
- **What the error means.** It is CTranslate2 failing to open `model.bin` inside a Hugging Face snapshot folder that exists but is incomplete. When a model comes from the cache (`local_files_only`, offline mode, or a failed connection), neither faster-whisper nor huggingface_hub checks that the snapshot is complete. So a partial download goes straight into `WhisperModel` (`model_loading.py:239-252`).
- **Partial downloads are likely.**
  - A 1.62 GB download with no byte progress (see 2) invites people to quit midway.
  - Quitting mid-download leaves `blobs/*.incomplete` and a snapshot without `model.bin`.
- **"On this PC" switches on offline mode.** `choice_changed` in `engine_ui.py` sets `offline_only`, which sets `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` (`gui.py:1937-1945`, `2565-2575`).
  - That blocks the very download that would repair the model.
  - Settings › Models then refuses downloads with "Offline mode is on".
  - huggingface_hub reads `HF_HUB_OFFLINE` when it is imported, so changing the variable later in the same process is unreliable in both directions.
- **First run opens the comparison check instead of preloading.** When `speed_checks.json` is missing, the app opens the comparison dialog (`gui.py:528-532`). The new dialog (`check_ui.py`) never writes that file, so a new user gets it at every start and never gets a preload.
- **The error itself is unhelpful.** It is raw, red, shows a cache path, and offers no action.

I could not open the owner's model folder, so which of these paths produced his partial snapshot is unconfirmed. F2 and F3 cover all of them.

### 2. TranslateGemma download: no progress, app blocked

- **Everything runs inside the GUI process.** Setup runs the download, SHA-256 check, model load and warm-up on a thread there (`quality_settings.py:232-290`).
- **No byte progress.** `snapshot_download(tqdm_class=…)` only counts files; huggingface_hub does not pass that class to the per-file download. The GGUF is one 2.49 GB file, so progress sits at 0% until the end. The same is true for the Whisper download and for Settings › Models (`model_loading.py:294-325`).
- **The app is blocked for the whole download.** `app.model_setup_busy = True` stays set throughout (`quality_settings.py:256`).
  - Start shows "Please wait…" and is disabled.
  - Device auto-refresh stops.
  - Manage keys, every setup dialog and the check all refuse to open. Manage keys shows "Finish the current session or setup first." (`gui.py:1610`), the hint in the owner's screenshot. The other dialogs give similar refusals (`gui.py:1592-1600`, `provider_settings.py:87`).
  - There is no cancel and no timeout. If the thread hangs, the flag never clears.
- **Errors are hidden.** Every failure becomes one generic sentence (`except Exception: pass`, `quality_settings.py:272`).
- **The model then loads in the GUI process too.** After the download it loads the 2.5 GB GGUF and warms it up in the GUI process using every physical core (`engines/mt_translategemma.py:86-90`, `125-134`).
- **The owner also saw a real hang.** I did not reproduce it. F3 moves the download, hashing and first load into a child process, which takes them out of the GUI process whatever the cause, and adds a test that the Tk loop keeps running.

### 3. White hover on tabs and buttons

I measured the app's own style code (`gui.py:542-690`) with Tk 8.6 and the `clam` theme:

| Style | Normal | Hover (`active`) | Pressed |
|---|---|---|---|
| `SegmentActive.TButton` | `#303033` / `#f3f3f5` | `#eeebe7` / `#f3f3f5` | `#bab5ab` / `#f3f3f5` |
| `Stop.TButton` | `#ff453a` / white | `#eeebe7` / white | `#bab5ab` / white |
| `TButton` (no style) | `#dcdad5` / black | `#eeebe7` / black | `#bab5ab` / black |
| `Treeview.Heading` | `#dcdad5` / black | `#eeebe7` / black | `#eeebe7` / black |
| `Dark.Vertical.TScrollbar` | `#303033` | `#eeebe7` | `#eeebe7` |

- **Why the tab turns white.** `SegmentActive.TButton` and `Stop.TButton` have no `style.map`, so hover falls back to clam's near-white with near-white text, a contrast of 1.07:1. The selected half of Listen/Speak and of App audio/Device uses `SegmentActive`, so hovering it shows a white box with an invisible label. That is the screenshot.
- **Unstyled buttons look light grey.** The `ttk.Button`s in `model_library_ui.py:39,67,69,71` have no style.
- **Table headers turn white on hover.** This affects the check dialog (`check_ui.py:31`) and Settings › Models.
- **The Settings sidebar has no hover.** It uses `tk.Button`.
- **Why the tests passed.** `test_all_entry_states_are_dark` only checks the entry `fieldbackground`.

### 4. Settings look unsaved

- **No feedback.** There is no Save button and nothing confirms that a change was saved.
- **Failed writes are silent.**
  - `SettingsState.set` writes the INI inside a Tk variable trace (`settings_state.py:40-48`). If the file is locked (antivirus, OneDrive, an open editor) or `write_config` raises, the traceback goes to stderr. In the windowed exe stderr is `None`, so nobody sees it.
  - Several writers do read-modify-write of the same `config.ini` with no shared lock: `SettingsState` and `persist_settings` on the UI thread, `ProviderSetup.test` on a worker thread, and save helpers for the engine, schedule and replies.
- **One setting lives in several places.**
  - "Offline" is spread over `UI.offline_only`, `UI.engine_profile`, `RUNTIME.offline_only`, `ENGINES.profile` and `ENGINES.engine_choice`.
  - The languages are in `UI.*` and also in `LANGUAGE` and `SPEAK`.
  - Startup reads the legacy sections, then overrides them from `UI.*` (`gui.py:408-483`). Session code reads other copies.
- **Text fields save every keystroke without validation.**
  - Typing `$10` writes `$10` to `ENGINES.monthly_cap_usd` (`engine_ui.py:16`).
  - `load_engine_settings` then reads that as $0, while the field still shows `$10`.
- **Opening the Engine page can overwrite the saved model.** `refresh()` replaces it with the first choice whenever the saved one is not in the list (`engine_ui.py:139-147`).
- **The Connect dialog looks like it forgot the key.** It empties the key field right after Test and every time it opens (`provider_settings.py:57,95`).
- **A provider can stop working with no visible reason.** Changing Account tier after a successful Test clears the tested signature (`engines/setup.py:118-127`).
- **Cloud falls back to this PC without explaining.** When Cloud is chosen but cannot be used, the session runs on this PC. The status bar says "Local" but not why.
- **Persistence is untested.** UI tests run with `TRANSLITO_UI_PREVIEW=1`, where `SettingsState` never writes (`gui.py:372`). Saving from real UI controls has never been tested.

### 5. Cloud setup is buried; the check is in the way

- **Using Soniox takes ten steps in three places.** Today a user must:
  1. Choose Cloud.
  2. Set a budget above $0.
  3. Open Manage keys.
  4. Pick a provider from raw ids.
  5. Paste a key.
  6. Change Account tier to `paid` (the default is `unconfirmed`).
  7. Set a separate per-provider limit above $0. Its default of $0 blocks every paid request.
  8. Press Test, which streams the public sample and is billed.
  9. Tick "Use this tested provider".
  10. Leave "Make this my default" ticked.

  If any one of these is missing, the session falls back to this PC without saying why (`engines/paid_streaming.py:44-52`, `engines/setup.py:101-112`, `engines/usage.py:268-310`).
- **The Engine page shows raw values.** Users see `local`, `stop`, `all`, `pair` and provider ids. The budget field appears on both Engine and Cost & usage.
- **The speed and accuracy check is everywhere.**
  - It opens by itself on first run.
  - It is the first button on the Engine page ("Run check", `engine_ui.py:127`).
  - It is the empty-state action ("Compare engines", `gui.py:1052`) and a Models button ("Check this PC's speed", `gui.py:1204`).
  - The engine cards tell you to run it.
- **Dead code.** `quality_settings.open_speed_check` is no longer reachable.
- **Unverified price.** Speechmatics is $0.20 per hour in code (`registry.py`, `paid_streaming.py`); the v2 handover listed $0.40 per hour undiscounted.

## Figma frames

Append `?node-id=<id with a dash>` to `https://www.figma.com/design/qHi2n6YF49UURgSJPYb6tB/Translator`.

| Frame | Node | Used by |
|---|---|---|
| 15 Settings · Engine · Connect cloud | 43:608 | F5 (not connected; budget at $0) |
| 16 Settings · Engine · Cloud connected | 43:772 | F5, F4 footer "Saved" |
| 17 Settings · Models and downloads | 44:679 | F2, F3, F5 (Compare engines moves here) |
| 18 Main · Background download and missing model | 45:709 | F2 hint, F3 status chip, F5 empty state |
| 19 Dialog · Local translation download | 45:817 | F3 |
| 20 States · Tabs, buttons and lists | 46:768 | F1 |
| Foundations (unchanged, plus new `color/red-hover`) | 10:41 | F1 token |

The settings frames are 760 tall to show the full page. The real window stays 820×680 and scrolls.

## Milestones

| Id | Milestone | Owner-visible result |
|---|---|---|
| F0 | Commit this handover on `codex/v2.1-fixes` and open the draft PR | Progress visible on GitHub |
| F1 | Interaction states for every widget | No white hover anywhere |
| F2 | Model files checked before loading; preload only when needed; no HF offline flags | No preload error; a missing model is a hint with an action |
| F3 | Background download manager in a child process | Real progress, continues while minimized, app never blocked |
| F4 | One settings store with validation, error reporting and a visible "Saved" | Changes visibly save and stick |
| F5 | Cloud setup on one page; checks out of the way; engine status says why | Provider, key, Connect, budget: done |
| F6 | Full check, docs, version 2.0.1, merge into v3 | Ready for the owner to test and release |

### F0. Handover and PR

- **Commit this file.** Add `CODEX_HANDOFF_V2_1_FIXES.md`. If a v3 commit already swept it up, restore it with `git checkout codex/v3-languages-landing -- CODEX_HANDOFF_V2_1_FIXES.md`.
- **Open the draft PR.** Its body is the F1–F6 checklist plus links to frames 15–20.

### F1. Interaction states (frame 20)

- **Theme code.**
  - Move all ttk styling into `ui_theme.py` as one `apply_theme(root, style, colors)` called by the main window and every dialog.
  - Add one helper for button-like styles that sets `background`, `foreground`, `bordercolor`, `lightcolor`, `darkcolor` and `focuscolor`. It maps states in this order: `("disabled",)`, `("pressed", "!disabled")`, `("active", "!disabled")`.
  - Use the frame 20 values for selected tab, unselected tab, Secondary (`Mac`), `Icon`, `Primary`, `Stop`, sidebar item, table header, dropdown/input and scrollbar.
- **New colour token.** Add `COLORS["red_hover"] = "#ff5f56"` to match the Figma variable `color/red-hover`.
- **Defaults.**
  - Configure the base `TButton` to look like Secondary, so a button without a style is never light.
  - Configure `Treeview.Heading`, every `*.TScrollbar` and `TCheckbutton`/`TRadiobutton` (where ttk versions are used).
- **Selected tab.** Hover changes nothing (frame 20, first row). Keep keyboard focus visible with a `blue` outline, not a fill change.
- **Settings sidebar.** Add hover with `<Enter>`/`<Leave>`: `surface-2`/`text`. A selected item stays `surface-2`/`text`.
- **Tests.**
  - Collect every style name used anywhere in the code (scan for `style="…"` and `.configure(style=…)`) plus `TButton`, `Treeview.Heading` and the scrollbars.
  - For each style and each state in `()`, `("active",)`, `("pressed", "active")`, `("focus",)`, `("disabled",)`:
    - background relative luminance is below 0.35;
    - for enabled states, text/background contrast is at least 2.9:1. This is the lowest pair in the current palette: white on `blue-hover`.
  - Add a regression for exactly the screenshot: the hover of `SegmentActive.TButton` is `field`.

### F2. Model files and preload

- **Model status.** Add `engines/model_files.py`, which reports one status per model.
  - The statuses are `Ready`, `Incomplete(have_bytes, total_bytes)`, `Missing` and `Corrupt`.
  - Required files:
    - CTranslate2 Whisper: `model.bin`, `config.json`, and `tokenizer.json` or `vocabulary.*` (plus `preprocessor_config.json` when the repo has one).
    - GGUF: the manifest file and its size.
  - Expected sizes come from a small local manifest written at download time (F3), with the repo, revision, file names, sizes and the LFS SHA-256 when Hugging Face provides it. For models cached before 2.0.1 (no manifest):
    - `Incomplete` if a required file is missing or a `blobs/*.incomplete` file exists for that repo;
    - otherwise `Ready`.
- **Loading.**
  - `_load_uncached` checks the status first. It passes the resolved local folder to `WhisperModel` with `local_files_only=True`, never an alias.
  - Loading never downloads. Downloads only happen in F3.
  - A status other than `Ready` raises `ModelNotReady(spec, status)`.
  - Map CTranslate2's "Unable to open file 'model.bin'" to `Incomplete`, and other load errors on an existing file to `Corrupt`.
- **Fallback.** When the chosen local model is not ready, the session uses the next ready local model, in the order Turbo → Small → Base.
  - If none is ready, use Cloud if it is connected and has a budget.
  - Otherwise the Start button says "Download Whisper Small (484 MB) to start". It starts the F3 download and stays enabled.
- **Messages.** These are yellow hints with an action (frame 18), never red errors, and never show a cache path:
  - "Whisper Turbo isn't fully downloaded (0.42 of 1.62 GB). Sessions use Whisper Small until it finishes." with the action Resume download.
  - `Corrupt` uses "Repair". It downloads that file again.
- **Preload policy.**
  - Preload at startup only when the chosen engine is On this PC, and only models that are `Ready`.
  - With Cloud or Free cloud allowances, load the local fallback in the background when a session starts. Never at launch.
  - Preload never shows an error.
- **Offline flags.**
  - Stop setting `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` anywhere in the app process.
  - "On this PC" means meeting audio and text stay on this PC; it no longer blocks model downloads.
  - Replace `offline_only` with an Advanced switch, "Never connect to the internet (blocks cloud and model downloads)", key `NETWORK.block_all`, default off.
  - The engine choice no longer changes this switch. `OFFLINE_ONLY` stays as the internal network gate, derived only from `block_all`.
- **First run.** Remove the automatic check dialog (`gui.py:528-532`). First run preloads by the policy above. Delete `quality_settings.open_speed_check`.
- **Tests.**
  - A fake HF cache with a snapshot missing `model.bin` plus an `.incomplete` blob gives `Incomplete`, `WhisperModel` is never constructed, and the hint text matches frame 18.
  - Corrupt file gives Repair.
  - The fallback order holds.
  - No preload at launch for Cloud.
  - `os.environ` never gains `HF_HUB_OFFLINE` during startup, preload or session start.
  - Choosing On this PC still allows a download.

### F3. Background downloads (frames 17, 18, 19)

- **Parent side.** `engines/downloads.py` holds `DownloadManager` in the GUI process.
  - It keeps a queue of jobs (one active, the rest queued) for Whisper models, the Arabic code-switch model, Cohere, TranslateGemma and Settings › Models.
  - Jobs run in a child process: `Translito.exe --download-job <job.json>` when frozen, `python gui.py --download-job <job.json>` from source. Handle the argument at the top of `gui.py` next to `--check-runtime`, before Tk, tray, hotkeys or audio start.
  - On Windows, start the child with `CREATE_NO_WINDOW` and below-normal priority.
- **Child side.**
  - Use `hf_hub_download` per file with resume, so `.incomplete` files continue.
  - Report progress by polling the growing file's size every 250–500 ms. This works for both HTTP and Xet transfers and does not rely on tqdm.
  - Write JSON lines to stdout, including `{"file", "bytes", "total", "bytes_per_s"}`.
  - Verify SHA-256 (the TranslateGemma manifest; Hugging Face LFS hashes for the others) and write the F2 manifest.
  - For TranslateGemma, also check the embedded chat template in the child, so the GUI process never loads the GGUF just to verify it.
- **Reading progress.** A reader thread puts lines on a queue. The UI polls it with `root.after(250, …)`. No Tk calls from any thread other than the main one.
- **Controls.**
  - Pause ends the child and keeps the partial file. Resume starts it again.
  - Cancel ends the child and keeps the partial file (frame 19 copy). Remove in Settings › Models deletes the model's files.
- **Stalls.** If nothing arrives for 60 s, show "Stalled · retrying". Retry three times after 10, 30 and 60 s, then show "Paused · check your connection" with Resume.
- **Disk space.** Before starting, require free space of at least the remaining bytes plus 500 MB. Otherwise say how much is needed and keep the folder picker.
- **Quitting.** Quitting with a download running asks once: "Quit and resume the download next time?" An unfinished, uncancelled job resumes automatically at the next launch.
- **No global block.** Downloads no longer set `model_setup_busy`. Only the model being downloaded is unavailable. Sessions, settings, connecting a provider and device refresh all keep working.
  - Keep a per-model lock so a model cannot be loaded or deleted while it downloads.
  - Audit every other `model_setup_busy = True` (`gui.py:1750,2077`, `model_library_ui.py:148`, `provider_settings.py:98`, `quality_settings.py:105,169,256,344`, `virtual_mic_ui.py:118`). Keep it only where two operations truly cannot overlap, and say which one is running in the message.
- **UI.**
  - **TranslateGemma dialog** (frame 19).
    - Before Download: the terms checkbox, Save to with free space, and a primary button "Download 2.49 GB".
    - During the download it shows the progress card: bytes, speed and time left, "Cancel download" and "Continue in background".
    - Closing the window equals Continue in background.
  - **Status-bar chip** (frame 18), for example "↓ TranslateGemma 48%". Clicking it opens Settings › Models. The tray menu shows a disabled line with the same text.
  - **Settings › Models** (frame 17) lists every model with Ready / Incomplete / Not downloaded / Downloading, sizes, and Pause, Cancel, Resume or Remove.
  - **When a download finishes**, show the existing schedule toast, for example "TranslateGemma is ready. It will be used from your next session." The chip disappears.
- **TranslateGemma load.** Load it lazily on the session worker thread at first use, with `n_threads = max(1, physical cores − 1)` so the UI keeps a core.
- **Tests.**
  - Use a fake fetcher module, passed in the job file, that writes 20 MB in timed chunks.
  - Progress goes up steadily and reaches the total.
  - Pause/Resume continues from the partial size.
  - Cancel keeps the partial file.
  - A stall triggers the retries.
  - A checksum mismatch reports a readable error and does not publish the path.
  - Not enough disk space is refused before starting.
  - A queued second job runs after the first.
  - With a real Tk root and a 5 s fake download, a 50 ms `after` heartbeat never gaps more than 250 ms.
  - The provider-connect action and Start stay enabled during a download.

### F4. Settings store and visible saving (footer in frames 15–17)

- **One store.** Add `settings_store.py`: one `SettingsStore` per config path, with an in-memory copy, one process-wide lock and a writer that coalesces writes. Text fields wait 400 ms after the last keystroke; toggles and dropdowns save at once.
  - Everything writes through it, including the engine, provider, schedule, reply, subtitle, hotkey, window-geometry, last-page and meeting-app saves, and worker threads.
  - Keep `write_config`'s preserving writer.
  - If the file is locked (`PermissionError`), retry five times with a backoff of 100 ms doubling to 1.6 s.
- **Feedback.** The Settings window gets the footer from frames 15–17:
  - "Changes save automatically" on the left.
  - On the right, "✓ Saved" for 2 s after each successful write.
  - On a failed write: "Couldn't save: <plain reason>. Retrying…", then "Couldn't save: <plain reason>" with Retry. It stays until a write succeeds.
- **One key per setting.** Add `settings_schema.py` with one entry per setting: section, key, type, default, validator, display labels, and whether it applies live or from the next session.
  - Keep the legacy sections (`LANGUAGE`, `SPEAK`, `RUNTIME`, `ENGINES`, `HOTKEYS`, `CAPTURE`) as the single source, so that an older build still reads them.
  - Stop writing the `UI.*` duplicates of `CONTROL_VARIABLES`.
  - One-time migration at first 2.0.1 start: where a `UI.*` duplicate differs from its legacy key, the `UI.*` value wins (2.0.0 wrote it on every change). Write the legacy key, then remove the duplicate.
  - Engine and network:
    - `ENGINES.engine_choice` (`cloud`, `local`, `free`) is the only engine selector, and `ENGINES.profile` is derived from it.
    - An old `offline_only=1` migrates to `engine_choice=local` with `NETWORK.block_all=0`.
- **Validation.**
  - Money fields accept `5`, `5.5`, `$5` and `5.50`, and save `5.00`. Anything else shows red helper text under the field ("Enter an amount like 5 or 12.50") and is not saved.
  - Comboboxes show display labels and store values:
    - fallback: `local` → "Continue on this PC", `stop` → "Stop the session";
    - scope: `all` → "All language pairs", `pair` → "This language pair";
    - warning: "80%";
    - providers by their titles.
- **No automatic overwrites.** Automatic choices must not overwrite saved user choices:
  - `refresh()` on the Engine page (`engine_ui.py:139-147`);
  - a fallback device picked because the saved device is missing for now;
  - anything set during startup.
- **Next-session settings.** While a session runs, changing a setting that only applies from the next session shows "Applies when you start the next session" under the control.
- **Test harness.** Add one that starts the real `TranslatorGUI` with writes on, and with hotkeys, tray, device polling, preload, network and Credential Manager replaced by fakes. Keep `TRANSLITO_UI_PREVIEW` for screenshots only.
- **Tests.**
  - For every setting in the schema: change it through its widget, close the app, start a new instance on the same file, and check that the widget value and the value the session would use are the same.
  - The migration works on a 2.0.0-style config.
  - Invalid money is not saved and the helper shows.
  - A locked file shows the retry, then the error.
  - A write from a worker thread cannot undo a newer UI change.
  - Opening the Engine page writes nothing.
  - The "✓ Saved" footer appears after a write.

### F5. Cloud setup on one page (frames 15, 16, 17, 18)

- **Engine page** (frames 15 and 16).
  - **Three cards:** Cloud, pay as you go / On this PC / Free cloud allowances. Each card has one line of description and a price on the right.
    - Remove the Delay and Accuracy columns, "not measured" and "run a check".
    - The price comes from the provider registry for the current pair.
  - **Cloud provider section**, shown when Cloud is chosen:
    1. **Provider** dropdown. Each entry has a title, what it does and its price. Soniox is listed first and selected by default, as recognition and translation in one stream at $0.18 per hour. ElevenLabs and Speechmatics are listed as "recognition; translation on this PC" with their prices.
    2. **API key** field, with the link "Get a key from <provider> ↗" and a primary Connect button. Under it: "Translito checks the key with <provider> without sending any audio, then keeps it in Windows Credential Manager."
    3. **Monthly budget** with "When the budget is used up" (Continue on this PC / Stop the session).
       - At $0 the orange helper reads "Paid use starts once the monthly budget is above $0. Until then sessions run on this PC."
       - Above $0 a grey helper gives hours at the list price and the 80% warning.
  - **After Connect,** a status card (frame 16) shows "Connected to <provider>" and "Key ending 7f3a · checked today at 10:42", with Replace key and Remove.
    - Get the last four characters from the store when the page opens. Never write them to the INI.
    - A saved key under an old 2.0.0 signature shows "Saved key found · Check again". Check again is a one-click check that needs no paste.
  - **Advanced** (collapsed) holds what this path drops: a separate translation provider, per-pair defaults, model versions, per-provider limits (default "Use the monthly budget"), the Azure region, and data-use consent for free tiers that reuse data.
  - Remove the budget duplicate from Cost & usage. That page shows usage and links to the Engine budget.
- **Free key check.** Connect makes no paid call and sends no audio. Use each provider's free authenticated endpoint, and confirm it in the provider's current docs before coding:
  - Soniox: `GET https://api.soniox.com/v1/models` with `Authorization: Bearer`.
  - Speechmatics: `GET https://asr.api.speechmatics.com/v2/jobs/?limit=1` with Bearer.
  - ElevenLabs: `GET /v1/user` with `xi-api-key`.
  - Gemini: list models.
  - Groq: `GET /openai/v1/models`.
  - DeepL: `GET /v2/usage`.
  - Google Translation: list languages with the key.
  - Cohere: list models.
  - Azure Translator has no free check. Send a one-character text request and say so in its privacy note.

  The outcomes:
  - 200 → connected.
  - 401/403 → "That key was rejected by <provider>."
  - Network error → "Couldn't reach <provider>. Check your connection."
  - Anything else → "<provider> returned an error (code N). Try again later."
- **Signatures and limits.**
  - The tested signature becomes `sha256(provider, key)`. Account tier is no longer something the user picks: providers under Cloud are paid, providers under Free cloud allowances are free.
  - A per-provider limit left empty means "use the monthly budget". Keep `$0 budget blocks every paid request` true.
- **Main window.**
  - The status-bar Engine field shows the engine actually running and, when it differs from the choice, why. It is orange and clicking it opens Settings › Engine. Reasons:
    - "On this PC · Soniox isn't connected"
    - "… key rejected"
    - "… needs a monthly budget"
    - "… budget used up"
    - "… internet is blocked"
    - "… doesn't support this language pair"
    - "… couldn't be reached"
  - The same reason goes in the transcript gap line when a fallback happens mid-session.
  - The empty state (frame 18) offers "Set up cloud", which opens Settings › Engine with the key field focused, plus "Keep using this PC". "Compare engines" goes away.
- **The check.** Remove "Run check", "Check this PC's speed", the empty-state button, the first-run dialog and "Connect providers" inside the check.
  - Keep `CheckRunner`, `CheckStore` and the dialog, opened only from Settings › Models › Tools › "Compare engines on a sample" (frame 17).
  - The dialog never asks for keys. It uses providers that are already connected.
- **Prices.** Verify Speechmatics' and ElevenLabs' current list prices. Show the undiscounted list price and record the date in `RATE_CHECKED_ON`.
- **Tests (mocked HTTP and credential store).**
  - Paste, Connect and the status card, with the key stored in the fake store and no audio sent.
  - A $0 budget gives the "needs a monthly budget" status and builds no paid router.
  - At $5 the Soniox router builds.
  - Remove deletes the key and the signature.
  - A rejected key shows the message.
  - The first run opens no dialog.
  - None of the removed buttons exist.
  - The check opens from Models only.
  - Every v2 cost-guard test still passes.

### F6. Check and hand back

- **Tests.** Run the full suite and fix any failures.
- **Version.** Bump `installer/VERSION` to `2.0.1`. Do not build or publish anything.
- **Docs.**
  - Write `docs/quality/RELEASE_2_0_1.md`: what changed for each of the five complaints and the test that covers each.
  - Update `docs/quality/IMPLEMENTATION_STATUS.md`.
- **PR.** Tick the checklist and mark the PR ready for review.
- **Merge into v3.** Merge into `codex/v3-languages-landing` as in "Order of work" step 5. The v3 language work must keep F1 (theme), F4 (store and schema) and F5 (registry prices and engine status) when it touches those files.

## Config changes

- **New:**
  - `NETWORK.block_all` (bool, default 0).
  - `ENGINES.<provider>_monthly_cap_usd`: empty means use the monthly budget.
  - Model manifests in `%LOCALAPPDATA%\Translito\models\manifest.json`.
  - Download jobs in `%LOCALAPPDATA%\Translito\downloads\`.
- **No longer written** (migrated once, then removed):
  - `UI.<name>` for the names in `CONTROL_VARIABLES`;
  - `RUNTIME.offline_only`;
  - `UI.offline_only` and `UI.engine_profile`;
  - `ENGINES.<provider>_account_kind`, which is derived instead.
- **Unchanged meaning:** budgets, `fallback_on_budget`, `budget_warn_percent`, cost-guard keys, hotkeys, schedule, replies, subtitles.

## Done means

- The suite passes, and every test named in F1–F5 exists.
- The new tests reproduce each of the owner's five complaints and pass:
  - a partial snapshot gives a hint, not an error;
  - progress goes up and the UI heartbeat holds during a download;
  - hovering the selected tab is not light;
  - a value survives a restart and a failed write is visible;
  - Connect works in one page with no check.
- No paid call, no real key, no real download and no Credential Manager read in any test.
- Nothing pushed to `main`; no tag, release or workflow run.

## Left for the owner

- Live test with his Soniox key: Settings › Engine › Cloud › paste key › Connect › budget, then a real Arabic meeting.
- Live test of the TranslateGemma download (2.49 GB) and of resuming the incomplete Whisper Turbo.
- Review and merge the v2.1 PR, then build and publish 2.0.1, or ask Codex in chat to build it.
- Decide whether the hover colours should get darker for more contrast. White on `blue-hover` and on `red-hover` is just under 3:1 in the current palette.

## Pitfalls

- huggingface_hub checks its offline flag when it is imported, and it serves cached snapshots without a completeness check. Never rely on environment variables or on the cache being complete.
- The PyInstaller child must exit before importing Tk, pystray, keyboard or audio, or it will show a second tray icon and register hotkeys twice.
- Never call Tk from a reader or worker thread. Use queues and `after`.
- Windows can hold `config.ini` or a `.gguf` briefly (antivirus, indexer, OneDrive). Retry, then report. Never fail silently.
- The `clam` theme's light defaults come back for any style or state you don't map. The F1 test must collect styles from the code, not from a hand-written list.
- Don't put the last four characters of a key, or any other key material, in `config.ini` or in logs.
- Keep the v2 cost guarantees: local speech and language gating before any paid stream, and reserve-before-call in the ledger.
