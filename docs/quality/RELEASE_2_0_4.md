# Windows 2.0.4

Explicit Resume now makes an automatic model download user-controlled. Language
changes and automatic setup refreshes can no longer immediately pause it again;
the intent also persists across restart. Automatic resumes still follow the
current language pair and required-model priorities.

HTTP/Xet transfer callbacks provide progress before buffered files reach disk,
preventing a receiving transfer from being mistaken for a stall. File sampling
tolerates atomic temporary-file renames. The next file returns to Downloading
after the preceding file is verified. Resumed workers can report fresh activity
below the saved visible byte count without being incorrectly marked stalled.
Temporary connection/server errors use
bounded retries, while access errors show a setup explanation. SDK URLs and
credentials are excluded from these messages.

The app opens on Listen even after a Speak session. Speak languages and device
choices remain saved, and the idle toggle shortcut starts the selected tab.
Single empty-state actions are centered; the two initial setup choices remain
inline with equal width and height. Native rendering retains the dark theme and
the existing 800×640 main-window dimensions.

## Verification

Regression checks cover explicit versus automatic Resume, language changes,
restart, buffered progress, retryable server failures, per-file download state,
Listen startup and both single/paired action layouts. A real Whisper Base transfer
completed in the actual frozen executable with Pause/Resume while automatic setup
reconciliation continued. The final complete regression suite passed **861 tests**,
including per-file state and resumed-worker progress checks. The frozen
executable passed all **19 runtime checks**.

The Windows packages reuse the verified native runtime and rebuild the changed
Python archives. Both added imports already exist in the bundled dependency
archive. Both the entry-point and importable GUI copies match the source; the
other **9,747 Python modules** and **14 archive entries** are unchanged.
Native rendering confirmed a zero-pixel horizontal offset for the single action
and equal-size paired actions. The portable ZIP passed complete CRC verification;
all 19 checked production modules and the importable GUI copy match the tested
source. Bundled engine data and VB-CABLE files match their sources. The existing
macOS 1.0 DMG is retained. Windows binaries remain unsigned.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.4.exe | 256,925,431 | `42586a1d36c2adb7297dc8db9eb97702d6180358ab54b4f93d94f8626afc2d1f` |
| TranslitoPortable-2.0.4.zip | 374,095,166 | `f4c00fde77a31af9d320d73489dc1c863f24a1f5f3e977267367df7a2f99356a` |
| Translito.dmg (retained 1.0) | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |
