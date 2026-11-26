# Windows 2.0.3

Session setup, the primary action, the engine badge and session startup now share
one readiness plan for the active Listen or Speak language pair. New installs
start with On this PC and prepare a basic local setup automatically. Saved cloud
preferences are retained. A cloud session prepares a small speech filter without
requiring optional local translation models before starting.

Changing languages reprioritizes automatic downloads for the new pair. Shared
files and partial downloads are reused; obsolete automatic jobs pause. User Pause
and Cancel remain in effect across pair changes and restart. The main window
shows current progress with Pause/Resume and Cancel, alongside Models and tray
controls. Larger and gated models remain explicit choices.

Budget edits apply only after validation and debounce, Enter, blur or Start.
Invalid or incomplete money text keeps the previous live budget. Engine and
language edits apply next session; internet blocking stops capture and background
downloads immediately. Cloud stages are resolved independently, including Soniox
recognition followed by an explicitly selected local translator.
Explicit recognition-stage choices also take precedence in Free mode. Live
global/provider caps, fallback policy and warning thresholds survive recovery.

Temporary streaming failures can recover on new utterances with backoff. Silence
does not open paid health-check streams, and locally processed utterances are not
replayed to cloud on recovery. Rejected credentials require reconnection. The
saved cloud preference is never replaced by a fallback route.

Stop cancels pending startup intent and discards late startup callbacks.
Scheduled capture is pending until capture actually starts, owns only its own
session, and checks the selected capture source. Calendar failures prevent starts
from stale cached events. Model-ready notices offer Models and Dismiss. Replies
off cancels pending generation and playback. Save failures retain transcripts for
retry, and failed shortcut changes restore the previous working registrations.

Native rendering was inspected at the existing 800×640 main window and 820×680
Settings dimensions. Controls retain the dark theme and existing centered window
placement. The macOS DMG remains the existing 1.0 build. Windows signing is
unchanged.

## Verification

- Final complete source suite: **847 passed** in a serial run, with the existing
  Torch deprecation warning. A prior run hit three child-startup timeouts; the
  worker checks passed separately and then passed within the complete rerun.
- Tests cover current-pair download priority, cached model reuse, model
  overrides, sticky Pause/Cancel across restart, explicit Resume, network
  blocking, valid budget commits, startup cancellation, repeated Stop,
  scheduled-session ownership and stale streaming callbacks.
- No real credentials, paid requests, driver installation or physical audio
  capture were used. Those integrations still require device/provider testing.

- The frozen executable passed all **19** runtime dependency checks.
- The portable ZIP passed a complete CRC check. All bundled engine data and
  VB-CABLE redistribution files match the sources.
- All **19** changed production modules in the actual EXE/PYZ match the tested
  source, excluding only source-location metadata.
- The final budget/route correction reused the verified native runtime. PyInstaller's
  archive writers rebuilt three Python modules with no new module imports;
  **9,748** other Python modules and **15** other archive entries were unchanged.
  The rebuilt executable passed the complete runtime probe in isolation.
- Installer and app both report **2.0.3**. Authenticode reports **NotSigned** for
  both; no signing certificate or Windows reputation change is claimed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.3.exe | 256,922,554 | `099d5f715e59d64f1fcb3d51ea15fae5b4df95757b85a223d1b1b67a8d456c38` |
| TranslitoPortable-2.0.3.zip | 374,093,109 | `ccc668aedf76373b1f3e3f157c915d03cd4e3bd700b08a8b32ae1da2387cd6b2` |
| Translito.dmg | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |

Runtime, package/source and signing reports, the dependency snapshot and SHA-256
manifests accompany the release. The macOS DMG is the retained 1.0 build.
