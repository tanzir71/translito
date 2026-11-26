# Windows 2.0.0

The main Listen window now has App audio and Device buttons above its source
picker. Switching restores the previous device or explicitly selected app;
browser selection includes the whole browser's audible process tree. The source
and language dropdowns share a baseline within the 800×640 default window.

An explicit Device choice bypasses meeting-app resolution, including its waiting
and all-app fallback rules. A previously saved meeting default remains available
when App audio is chosen again. Explicit app and All apps selections also take
priority over that default. Changing capture type cancels pending app polling;
switches lock during recording. The Settings Audio page shares the same state.

This release also packages the completed v2 source milestones: dark controls,
sidebar Settings, transparent icons, delay/usage tracking, opt-in paid streaming,
budget/cost guards, comparison checks, desktop subtitles, schedules and replies.
Paid requests start with a $0 budget and require connected/tested accounts.

Automated regression verification uses `python -m pytest -q`. Packaging uses a
separate CPU-only environment and the frozen EXE's expanded dependency/CPU probe.
No installer is run on the owner's installation, and no real credentials,
calendar, provider inference or physical audio devices are used for release checks.

Windows artifacts are versioned Setup and portable ZIP files, accompanied by
SHA-256 checksums and the frozen runtime report. The macOS DMG carried in this
release is the existing 1.0 build, unchanged; the Python/Windows v2 features are
not represented as native macOS features.
