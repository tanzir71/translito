# Windows 2.0.4

Explicit Resume now makes an automatic model download user-controlled. Language
changes and automatic setup refreshes can no longer immediately pause it again;
the intent also persists across restart. Automatic resumes still follow the
current language pair and required-model priorities.

HTTP/Xet transfer callbacks provide progress before buffered files reach disk,
preventing a receiving transfer from being mistaken for a stall. File sampling
tolerates atomic temporary-file renames. The next file returns to Downloading
after the preceding file is verified. Temporary connection/server errors use
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
reconciliation continued. The full regression suite passed **859 tests**; all
**15 download tests** passed again on the final source, including the final
per-file state correction. The frozen executable passed all **19 runtime checks**.

The Windows packages reuse the verified native runtime and rebuild the changed
Python archives. Both added imports already exist in the bundled dependency
archive. The other **9,748 Python modules** and **14 archive entries** are
unchanged. Native rendering confirmed a zero-pixel horizontal offset for the
single action and equal-size paired actions. Packaged source, archive CRC and
resource checks precede publication. The existing macOS 1.0 DMG is retained.
Windows binaries remain unsigned.
