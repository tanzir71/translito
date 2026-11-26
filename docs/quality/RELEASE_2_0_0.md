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

## Verification and artifacts

- `python -m pytest -q`: **504 passed**, one existing Torch JIT deprecation warning.
- Source: `4bfb195d6462b1dd5cc48e098bc6a0ffe3f841ac` on `main`.
- Fresh CPU build: Torch 2.13.0+cpu, Transformers 5.22.1, Python 3.13.
- Frozen EXE: ProductVersion/FileVersion 2.0.0; all **18** dependency checks and
  the native CPU tensor calculation passed. Every engine data file matched its source hash.
- Portable ZIP: complete CRC pass, with the EXE, UI/tray icons and process-loopback
  DLL present. No speech-recognition/translation model weights or owner
  settings/transcripts are bundled.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| TranslitoSetup-2.0.0.exe | 256,616,371 | `d7e3a2d402fee8607c59b597f7fa9c96d0f56381d9d369325cc2aaa56becf235` |
| TranslitoPortable-2.0.0.zip | 373,821,341 | `70027b4083645f3a44071b77aa3caa8de942cd597d7bc75dd8f9991b73e4b04b` |

The release includes `runtime-check.json`, `build-requirements.txt` and
`SHA256SUMS.txt`. [Windows 2.0.0 release](https://github.com/tanzir71/translito/releases/tag/v2.0.0).
All six uploaded asset sizes and SHA-256 digests matched the local files before
publication. Published as latest on 2026-11-26; its tag targets the tested source
commit above. The follow-up commits update release documentation only.
