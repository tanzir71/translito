# Windows 1.1.1 release validation

The patch preserves the selected Fast/Balanced/Best decoder beam size when the
bilingual recognizer loads a prepared Arabic code-switch fallback. Previously,
both missing Cohere weights and a runtime Cohere failure could silently reset
the replacement recognizer to Balanced. Model choices and fallback order are
unchanged. No model weights or provider credentials are bundled.

Validation before packaging: **351 tests passed**, including six cases checking
the real Whisper adapter's decoder arguments after both kinds of fallback.
The existing Torch JIT deprecation warning remains. Installer VERSION, Inno and
EXE resource versions agree on 1.1.1. The source revision used for the build is
`0674c3b261f5a3626ce5f4d29486f5b4d4e189a1`. Artifacts are retained under
`D:\TranslitoReleases\1.1.1\build-01`. The release is installed, verified and
[published](https://github.com/tanzir71/translito/releases/tag/v1.1.1).

## Frozen and installed checks

- A fresh compact PyInstaller stage includes the checked engine data. The
  frozen EXE opens from `C:\Windows\System32` with an isolated profile,
  cached Small/Marian and the Offline profile. After Ready and LID readiness,
  it captured the public 8.16-second FLEURS clip from owned Python parent PID
  2512 / rendering child 28844, displayed an AR source row and English target,
  returned to Ready on Stop and saved a 717-byte isolated transcript. The
  fallback wording is weak; this is functional smoke evidence only. The build
  was also compressing during playback, so this is not a latency measurement.
- One test launch using inherited terminal output handles showed an
  "Invalid argument" preload error. The same unchanged binary loaded with retained log handles;
  the subsequently installed copy opens normally through the desktop launcher.
  No speculative production fix was made for the test-launcher failure.
- The installer exited 0 and requested no reboot. Installed ProductVersion is
  1.1.1 and its EXE SHA-256 matches the staged executable. Its normal app window
  is open in the owner's existing Speak/Ready state with zero entries; no
  microphone recording was started.
- The original 1,804-byte config is byte-identical before and after installation
  and GUI startup. All five existing transcript hashes match, no usage file was
  created, and all 30 previous distribution metadata files match the retained
  runtime archive. Prior runtimes and the failed test artifacts are preserved.
- All four uploaded asset sizes and SHA-256 digests match the local files.
  Both direct Windows downloads and the latest macOS DMG return HTTP 200.
- Hugo builds the updated Windows 1.1.1 links successfully. Download-page and
  workflow source now target the verified release; deployment verification is
  tracked in [PR #15](https://github.com/tanzir71/translito/pull/15). The existing
  macOS 1.0 DMG is carried unchanged to preserve its latest-download URL.

## Artifacts

- `TranslitoSetup-1.1.1.exe`: 256,350,306 bytes, SHA-256
  `f39fbcd4739d7bc19235d534850722016b2963b91ee8bf724d2ec6fd452d525f`.
- `TranslitoPortable-1.1.1.zip`: 373,772,712 bytes, SHA-256
  `7d29dddcee784cf92d54dff28a55ddb78627f9891c0bbf7280ab6c74747267f2`.
- Unchanged `Translito.dmg`: 6,044,398 bytes, SHA-256
  `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73`.

The cache-only bilingual switching report in LOCAL_HARDWARE.md independently
verifies EN → AR → EN rows and English no-MT behavior using synthetic English
and public MSA. It does not establish Saudi accuracy, gated Cohere performance
or the four-second latency target. Physical VB-CABLE routing and real provider
accounts remain unverified. The owner approved driver installation/test, but
Windows rejected the launch before a driver process started; the separate
manual Windows installation step remains pending. This app patch does not
change Windows settings or address that driver-launch failure.
