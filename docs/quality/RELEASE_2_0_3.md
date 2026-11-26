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

- Final complete source suite: **843 passed** in a serial run, with the existing
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
- Installer and app both report **2.0.3**. Authenticode reports **NotSigned** for
  both; no signing certificate or Windows reputation change is claimed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.3.exe | 256,927,119 | `da556b6f001b68d397a0075234a856e6682009b5af9df0ecfa9a874ff6e17f84` |
| TranslitoPortable-2.0.3.zip | 374,092,687 | `b1c6930f90fda9a3206872a7cd31d1ec48c93cf2baa8a4b9f6262631eb669233` |
| Translito.dmg | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |

Runtime, package/source and signing reports, the dependency snapshot and SHA-256
manifests accompany the release. The macOS DMG is the retained 1.0 build.
