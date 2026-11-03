# Windows 1.1.2 audio-thread fix

Source `01c22a7245471f250ca36d91b735f4a088615750` initializes Windows COM on
the thread doing SoundCard device enumeration, capture, virtual-mic testing or
transcript device-name lookup. A successfully installed cable previously failed
the physical self-test with `0x800401F0` when its recorder opened on a new thread.

The shared scope balances both S_OK and S_FALSE references on success/failure,
respects an existing STA apartment without uninitializing it, and is a no-op on
other platforms. SoundCard's first import runs before adding our reference,
because its own initializer rejects S_FALSE. No vendor library is modified.
Microsoft documents the [per-thread COM requirement and return values](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex).

Validation: **368 tests passed**, one existing Torch JIT deprecation warning,
41.18 seconds. Coverage includes real Windows worker apartment initialization
and balanced cleanup, mocked existing MTA/STA/failure cases, dependency import
order, enumeration/device properties, capture error handling and transcript
metadata. Existing cable tests now assert COM scope on both caller and recorder
threads. No paid provider was contacted.

## Physical driver and source checks — 2026-11-03 Bangladesh time

- The owner approved installation/test and later confirmed administrator
  approval and installation completion. The unchanged, hash-verified Pack45
  launched successfully from a unique `C:\Temp\TranslitoVBCable-*` folder after
  earlier app-data launches failed with error 3. Its setup signature and
  Microsoft Hardware Compatibility catalog signature were valid. This is a
  successful manual-layout workaround, not a proven diagnosis of error 3.
- The vendor GUI reported installation complete/successful and requested a
  reboot. Windows enumerated a working VB-Audio Virtual Cable device plus two
  duplicate failed-start nodes (code 10); SetupAPI says a reboot is needed.
  No restart, device removal or Windows security/privacy change was performed.
  Post-reboot enumeration and real meeting use remain to be checked.
- The original source self-test failed before playback at
  `microphone.recorder`, HRESULT `0x800401F0`. With the fix, the real desktop
  `self_test` passed: 1 kHz / 0.8-second tone, approximately **-16.846 dBFS** in
  the 950–1050 Hz band, above the **-30 dBFS** threshold. Only CABLE Input was
  played and CABLE Output recorded. No physical microphone, saved raw PCM or
  cloud inference was used.
- A fresh background caller with cold SoundCard import also passed at
  -16.846234 dBFS, and its worker stopped. This covers the GUI's nested worker
  arrangement rather than relying on initialization in the probe's main thread.
- The real `ArabicAudioTranscriber.capture_audio` worker received seven blocks
  from CABLE Output, max peak 0.400967 / RMS 0.180274, emitted no errors and
  stopped. That probe stubs preprocessing and runs no ASR/MT; it is capture/Stop
  evidence, not translation-quality or latency acceptance.

### Pre-reboot packaged check

The frozen 1.1.2 GUI opened from `C:\Windows\System32` with a separate Offline
profile, prepared Small/Marian cache and zero entries. Its actual **Test virtual
mic** action returned a failure: the recorder worker remained blocked in
SoundCard's `IAudioClient.Start` call (`mediafoundation.py:715`), rather than the
original COM-not-initialized exception. A subsequent source test stalled at the
same stage, including after closing the owned frozen probe. The original source
passes above are initial routing evidence, not a stable post-reboot acceptance.
The stalled isolated GUI was terminated; no physical mic/session was started.
Further physical tests await the vendor-requested restart. No packaged routing
pass, successful meeting or automatic reboot is claimed.

Local receipts, failed probes, scripts and upgrade baselines are preserved under
`D:\TranslitoReleases\1.1.2\validation-01`; the extracted vendor package remains
under `C:\Temp\TranslitoVBCable-220f98ab`. The before-upgrade baseline includes
the real 1,804-byte config, all five original transcript hashes, usage-file
absence and 160 installed runtime metadata files.

The pre-reboot check found VB-CABLE selected as Windows' default speaker/microphone. Use real
headphones for normal Windows/meeting playback and CABLE Output for the meeting
app's microphone. This release does not establish Saudi ASR/MT quality, gated
Cohere/Gemma performance or real cloud-account acceptance.

## Build artifacts

The compact PyInstaller stage is
`D:\CodexBuilds\Translito-quality\.p\79fb194e\d\Translito`. Its PYZ/Analysis
receipts include the new `windows_audio` module. Version metadata agrees on
1.1.2; the portable ZIP and Inno installer were rebuilt from the source revision
above. The optional driver task remains unchecked and is skipped by silent
upgrades. Artifacts are retained at `D:\TranslitoReleases\1.1.2\build-01`.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| TranslitoSetup-1.1.2.exe | 256,356,396 | `ea5d3947e0e79d086d108866198a97c159c93b03b65ba1e6582e0f77a3f20c3a` |
| TranslitoPortable-1.1.2.zip | 373,773,286 | `a9e1d7cd84e44edfa4cce3c35c25506b3563eaa62d45ffc74791fa2f00944566` |
| Unchanged macOS 1.0 Translito.dmg | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |

## Installed upgrade and draft release

The 1.1.2 application installer exited **0**, requested no restart and installed
ProductVersion 1.1.2. Its EXE SHA-256 matches the frozen stage. The real config
and all five original transcripts remain byte-identical; usage-file absence is
unchanged. All 160 previous runtime metadata files match their retained copies
in `runtime-history\20261103-022508`. The config also matched after normal app
startup. These are app-upgrade checks; they do not finalize the separate audio
driver's reboot requirement.

All four GitHub draft assets (Setup, portable ZIP, unchanged DMG and checksums)
matched local sizes and server SHA-256 digests. The draft targets the source
revision above. **Release publication and landing-page deployment remain
pending**; this branch stages the 1.1.2 download links. Desktop verification was
stopped when the owner pressed Escape. No installed GUI routing pass or
post-reboot acceptance is claimed.
