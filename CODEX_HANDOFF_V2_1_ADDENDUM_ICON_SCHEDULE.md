# Codex handover addendum: v2.1 icon and schedule fixes

This adds three milestones to `CODEX_HANDOFF_V2_1_FIXES.md`, which you are already working through. Don't restart anything.

- Finish the milestone you are on, then do F7, F8 and F9 below on `codex/v2.1-fixes`, after F5 and before F6.
- F6 (full check, version 2.0.1, docs, merge into v3) stays last and now also covers F7–F9.
- If F6 is already done, do F7–F9 on the same branch, then run F6's steps again.

Ground rules and git rules are the same as in the main v2.1 handover:
- Commit and push after each milestone with the id in the subject.
- Add F7–F9 to the draft PR checklist.
- No pushes to `main`, no merge into `main`, no tags, no releases, no workflow runs.
- Automated tests only; no real keys, downloads or Credential Manager reads.

Figma: page "Translito v2 · UX", frame **21 Settings · Schedule · Workdays (v2.1)**, node `47:767`. Link: `https://www.figma.com/design/qHi2n6YF49UURgSJPYb6tB/Translator?node-id=47-767`.

## The owner's feedback (26 Nov 2026)

1. The icon looks blurry in the Windows taskbar.
2. There's no easy way to set the schedule to start every day except two days off.

## What the audit found

Line numbers refer to `main` at `74287b9`.

### Icon

- **The tray uses the wrong artwork.**
  - It loads `engines/data/tray/<state>-64.png` (`gui.py:2661`).
  - `tools/build_icons.py` draws those 64 px images from the large mark, which has a thin ring and bars. The bold small cut is only used up to 40 px.
  - Windows shows tray icons at 16 px (100% scaling), 20 px (125%) and 24 px (150%), so it shrinks the 64 px thin artwork. I rendered both: the ring turns grey and soft. The `.ico` frames drawn from the small cut stay crisp white at the same sizes.
- **The window and taskbar icon is the tray artwork, rescaled.**
  - `gui.py:375-385` sets `iconbitmap(Translito.ico)`, then replaces it with `iconphoto(True, idle-32, idle-64)`.
  - The Windows 11 taskbar draws window icons at 24 px (100%), 30 px (125%) and 36 px (150%). Every one of those is a rescale of a 32 or 64 px image.
- **The `.ico` lacks some taskbar sizes.** `installer/Translito.ico` has 16, 20, 24, 32, 40, 48, 64, 128 and 256. There are no frames for 30, 36, 60, 72 or 96.
- **The app is DPI-unaware.**
  - PyInstaller's default manifest declares no DPI awareness (checked in the 6.22.3 source), and the app never calls `SetProcessDpiAwareness`.
  - At 125% or 150% scaling, Windows gives the app 96-DPI sizes and stretches its window and icons. That also blurs the app's text.
- **The shortcuts have no AppUserModelID.**
  - The Inno Setup shortcuts (`installer/Translito.iss`, `[Icons]`) have none, while the window sets `Translito.Desktop.v2` (`gui.py:2785`).
  - So a pinned shortcut and the running window are separate taskbar items, and the running one uses the soft window icon.

### Schedule

- **Weekly times take one day per entry.** `schedule_ui.py:122-152` has a Day dropdown, typed HH:MM start and end, "Add weekly time", and a three-row list. "Every day except Friday and Saturday" needs five separate entries.
- **Weekly times default to UTC.**
  - The "Time zone for weekly times" field defaults to `UTC` (`schedule_ui.py:21`) and is stamped into each entry when it is added.
  - So someone in Dhaka who enters 09:30 gets 09:30 UTC, which is 15:30 in Dhaka.
  - `weekly_meetings` also defaults to UTC (`engines/schedule.py:35`).
- **Raw values on screen.** The source is a raw `ical`/`weekly` dropdown, and the calendar-link field shows even when weekly times are chosen. The stop rule shows raw `end`/`silence`.
- **Open at login doesn't suit a daily schedule.**
  - The schedule only works while the app runs, but "Open at login" lives on the General page.
  - It opens the full window at every sign-in: the Run value is the bare exe path (`login.py`).
- **Downloads block scheduled starts.** A scheduled start is skipped while `model_setup_busy` is set (`schedule_ui.py:15`), so a model download blocks it.
- **Time-zone data may be missing.** Windows has no IANA time-zone database, and neither `tzdata` nor `tzlocal` is pinned. `ZoneInfo("Asia/Dhaka")` only works if `tzdata` is bundled.

## Milestones

| Id | Milestone | Owner-visible result |
|---|---|---|
| F7 | Sharp icons at every size: right artwork, exact sizes, matching shortcut ID | Crisp tray and taskbar icon |
| F8 | Schedule by days and one time range, in the PC's time zone; open at login starts quietly in the tray | "Every day except Fri and Sat, 09:30–18:00" in one step |
| F9 | System-DPI awareness with scaled layout (its own commit so it can be reverted alone) | Sharp icons and text at 125% and 150% |

### F7. Icons

- **Build every frame from the right artwork.** In `tools/build_icons.py`:
  - App ICO sizes: 16, 20, 24, 28, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128 and 256.
  - Use the small cut up to 40 px and the regular mark above that.
  - Render each size from the master at 4× with one LANCZOS downscale. Today the tray images are resized twice.
- **Tray icons.** Build `engines/data/tray/<state>.ico` for idle, listening and paused, each with 16, 20, 24, 28, 32, 40 and 48 px frames from the small cut plus the status dot. Keep the PNGs only for anything else that still reads them.
- **Contact sheet.** Add `python tools/build_icons.py --sheet`, which writes `docs/quality/icons-2.0.1.png`: the tray at 16/20/24/32 and the taskbar at 24/30/36/48, from both the old and the new pipeline, so the owner can compare them at a glance.
- **Window icon (main window, settings and every dialog).**
  - Stop using `iconphoto` with tray images.
  - On Windows, add `apply_window_icon(window)` to `ui_theme.py`. After the window is mapped it:
    1. loads `Translito.ico` with `LoadImageW(…, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)`, taking sizes from `GetSystemMetricsForDpi(SM_CXICON / SM_CXSMICON, dpi)` (or `GetSystemMetrics` if that isn't available);
    2. sends `WM_SETICON` for `ICON_BIG` and `ICON_SMALL` to the toplevel's HWND (`GetParent(winfo_id())`).
  - Keep `iconbitmap` as the fallback on errors and on other platforms.
- **Tray loading.**
  - Subclass pystray's Windows `Icon` so the tray handle is loaded from the state `.ico` at the exact small-icon size for the current DPI, instead of pystray saving one PIL image as a single-size ICO.
  - Pin the pystray version: this uses a private method. If the method isn't there, fall back to today's behaviour.
- **Installer.**
  - Add `AppUserModelID: "Translito.Desktop.v2"` to both shortcuts in `[Icons]`.
  - Read the ID from one constant shared by `gui.py` and the build. Don't keep two copies.
- **Tests.**
  - The ICO contains every size, with the small-cut frames at 40 px and below.
  - The tray ICOs contain every size.
  - `apply_window_icon` sends `WM_SETICON` with sizes from the mocked metrics.
  - No `iconphoto` call uses tray images.
  - The tray subclass asks for the exact small-icon size.
  - The `.iss` AppUserModelID equals the code constant.
  - The contact sheet builds.

### F8. Schedule (frame 21)

- **Data.**
  - New key `SCHEDULE.weekly_blocks`: a JSON list of `{"days": [0–6], "start": "HH:MM", "end": "HH:MM", "timezone": "<IANA>", "title": "optional"}`.
  - `weekly_meetings` accepts blocks and still reads the old `weekly_times` format.
  - An end time earlier than the start runs past midnight.
  - A day can belong to only one block.
- **Migration from 2.0.0** (one time).
  - Group old `weekly_times` entries that share start, end and time zone into one block.
  - If `SCHEDULE.timezone` is still the default `UTC` and the entries use `UTC`, the user almost certainly meant local time. Convert those entries to the PC's zone, keeping the clock times. Then show this once: "Weekly times now use your PC's time zone (Asia/Dhaka). Check them in Settings › Schedule."
  - If the user chose any other zone, leave it alone.
- **PC time zone.** Read the IANA name with `tzlocal.get_localzone_name()`. Pin `tzdata` and `tzlocal` in `requirements.txt`.
- **UI (frame 21).**
  - **Top of the page:** two switches.
    - "Start automatically for meetings".
    - "Open Translito when Windows starts", the same state as General › Open at login, with the caption "The schedule only runs while Translito is open in the tray."
    - If the schedule is on and open-at-login is off, show under the switch: "Turn this on so the schedule keeps working after a restart."
  - **Source** as two radio cards. Only the selected card expands: the calendar card shows its link field only when selected.
  - **Fixed weekly times card.**
    - **Day chips** that toggle, in the order of Windows' first day of the week (`LOCALE_IFIRSTDAYOFWEEK`; the frame shows Monday first). At least one day must stay on.
    - **Presets** "Every day", "Mon–Fri" and "Sun–Thu". Sun–Thu covers Friday–Saturday weekends such as Saudi Arabia and Bangladesh.
    - **From and To:** editable comboboxes in 15-minute steps.
      - They accept `9:30`, `09:30`, `0930` and `9:30 pm`, and save 24-hour `HH:MM`.
      - An invalid entry shows red helper text and is not saved.
    - **Time zone:** "Your PC's time zone · Asia/Dhaka · change". "Change" opens a searchable list of IANA zones.
    - **Summary** in green, generated from the selection. Examples:
      - "Every day except Friday and Saturday, 09:30 – 18:00 Dhaka time."
      - "Monday to Friday, …"
      - "Every day, …"
      - "Monday, Wednesday and Thursday, …"
      - "… (ends the next day)" when the range crosses midnight.
    - **"+ Different hours on some days"** adds a second block with its own chips, times and Remove. Chips already used in another block are disabled, with a tooltip saying which block has them.
  - **Start and Stop dropdowns** with display labels.
    - Start: "At the start time", "1 min before the start time", "2 min before", "5 min before".
    - Stop: "At the end time", "After 5 min of silence", "After 10 min of silence". Keep the stored values.
  - **Coming up:** the next three occurrences from either source, each with a switch to skip that one occurrence. Store skips in `SCHEDULE.skipped` and prune past entries.
  - **Footer:** the "Changes save automatically / ✓ Saved" footer from F4.
- **Open at login starts quietly.**
  - The Run value becomes `"<exe>" --tray` (from source: `"<python>" "<gui.py>" --tray`).
  - `--tray` starts in the tray with no window, no first-run prompts and no model preload unless F2's policy allows it.
  - At startup, if an existing Run value points to this exe without `--tray`, rewrite it.
- **Scheduled starts.** The scheduler's "running" check only looks at a real session (`app.transcriber is not None`), never at downloads or setup.
- **Frozen build.** Extend `runtime_check.py` to check `ZoneInfo("Asia/Dhaka")` and `tzlocal` in the frozen build.
- **Tests.**
  - Migration groups five same-time entries into one block.
  - The UTC-default migration and its one-time notice.
  - Another chosen zone stays unchanged.
  - Every summary sentence variant.
  - The presets.
  - Chip order from a mocked first-day-of-week.
  - Overnight ranges.
  - A day can't be in two blocks.
  - `weekly_meetings` across a DST change (Europe/Berlin) and in Asia/Dhaka.
  - Skipping an occurrence.
  - `--tray` creates no visible window and does set up the tray.
  - The Run value rewrite.
  - A scheduled start goes ahead during a fake download.
  - A settings round trip through the F4 harness.

### F9. DPI awareness with scaled layout

Keep this in its own commit so it can be reverted without touching F7 or F8.

- **Declare awareness.**
  - Use system-DPI awareness, not per-monitor: Tk 8.6 doesn't lay a window out again when it moves to a monitor with a different scale.
  - Add `installer/Translito.manifest`: PyInstaller's default manifest plus `<dpiAware>true</dpiAware>` and `<dpiAwareness>system</dpiAwareness>`. Pass it with `EXE(manifest=…)` in the spec.
  - For source runs, call `SetProcessDpiAwareness(1)` at the top of `gui_main` before `tk.Tk()`. Ignore the error you get if the manifest already set it.
- **Scale the layout.**
  - Set `scale = GetDpiForSystem() / 96`, and set `tk scaling` to `dpi / 72` so point-sized fonts follow.
  - Add `px(n)` and run every fixed pixel value through it:
    - window geometry and minimum sizes (800×640, 820×680, every dialog);
    - the 188 px sidebar, layout paddings and spacings, and `wraplength`;
    - canvas widgets (Switch 34×20, the level meter, progress bars) and Treeview row height;
    - subtitle overlay sizes and positions, and toast geometry.
  - Fonts already use points and need no change.
- **Saved window size.** Store the DPI next to `UI.window_geometry` and scale the saved size when the DPI has changed since it was saved.
- **Test override.** Allow `TRANSLITO_UI_SCALE` to force a scale.
- **Tests.**
  - At scale 1.0 the existing UI tests pass unchanged.
  - At 1.5 the settings window is 1230×1020, and on every settings page and dialog no widget extends past its parent's width.
  - A source-scanning test fails if a numeric `geometry(...)`, `minsize(...)`, `width=` or `wraplength=` literal is used without `px()`.
  - The manifest contains the DPI keys.
  - `gui_main` sets awareness before creating Tk (mocked `ctypes`).
  - `apply_window_icon` and the tray use the real DPI's metrics.

## Done means (added to F6)

- The F7–F9 tests exist and pass with the rest of the suite.
- `docs/quality/icons-2.0.1.png` is committed.
- `docs/quality/RELEASE_2_0_1.md` covers the blurry icon and workday scheduling, naming the tests that cover them.

## Left for the owner

- Look at the contact sheet. After installing 2.0.1, check the tray and taskbar at your normal display scale.
- Set the schedule on the Schedule page (for example Sun–Thu, 09:30–18:00) and confirm it starts on the next workday.
- If anything about the larger-scale layout looks off, F9 can be reverted on its own.
