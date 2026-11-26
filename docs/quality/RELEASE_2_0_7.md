# Windows 2.0.7

The reported download failure was reproduced as Windows error 448 with
RedirectionGuard enforced. The installer's default protection is inherited by
applications launched from its unprivileged post-install step. Hugging Face
snapshot symlinks created by the user were therefore blocked, while direct
launches used during earlier verification could read them. See the
[Inno Setup explanation](https://jrsoftware.org/inno-setup/documentation/topic_setup_redirectionguard.htm).

Windows downloads now materialize validated snapshot links as regular hard
links to their immutable model blobs, with a copy fallback. Blob contents are
retained and normal size/SHA verification remains required. Windows protection
is not disabled. Sixteen blocked files in the reported cache were repaired and
read successfully with the protection still enforced. Error 448 is no longer
classified as a transient connection failure.

A connected cloud recognizer no longer requires Whisper before admission or
capture. Local ASR loads only for fallback or optional background filtering.
Speech detection is available immediately; the language filter attaches once
its optional local model is available. Backup setup failures do not block an
otherwise ready cloud route. Explicit local translation still requires its
translation model. Local model runtimes are imported only when needed.

The ASR/MT router no longer emits an unsupported-default warning for the native
Soniox live route. Primary providers automatically resolve their single supported
model, including obsolete saved model IDs.

Stop signals capture immediately and performs cleanup outside Tk. Cleanup or
transcript-save exceptions return control and retain the transcriber in memory.
Streaming reservations settle in one transaction while preserving conservative
cost estimates. Download-worker creation runs outside Tk, and bursts of progress
events persist/render once per UI frame.

## Verification

The real Soniox service accepted the configured key and `stt-rt-v6`. With Windows
protection enabled and all local model loading forbidden, the bundled eight-second
public Arabic sample produced English translation. Approximately seven seconds
of speech were sent; runtime cleanup took 0.089 seconds. No microphone or customer
meeting audio was captured. The false model-selection warning did not occur.

The regression test reproduces blocked snapshot access under RedirectionGuard,
then checks that the repaired file remains readable with that policy enabled.
Other new checks cover capture without local models, optional filtering,
conservative batch settlement, progress coalescing and Stop/save failures.

Windows builds remain unsigned. The macOS 1.0 DMG is retained.

The final regression groups passed **861 app checks and 29 download checks**.
The latter includes cancellation while Windows is still creating the worker.
The frozen runtime passed all **21 checks**. With local models unavailable, the
frozen GUI completed Start with Soniox and returned from Stop to Start in
**0.31 seconds**, without Tk callback errors or microphone capture.

The portable archive passed full CRC verification and all staged file-size
checks. All 27 checked production modules and the importable GUI match source;
engine data and VB-CABLE resources match their sources. Thirteen Python modules
were rebuilt; 9,738 others and 14 archive entries are unchanged. Both raw and
importable GUI copies were updated and verified. Release source:
`9acfd7391d7cdbc9f1934e09806b56f83d54ea4e`.
The landing page passed **64 checks** with the 2.0.7 download links.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.7.exe | 256,925,583 | `9db54836c3178442b0974192ac456655a5718811a9c149bcfce9423ebde19837` |
| TranslitoPortable-2.0.7.zip | 374,107,689 | `899b34b799a0f3813a12813d86ceb051f6091399c18e30529790965a4d7faa7f` |
| Translito.dmg (retained 1.0) | 6,044,398 | `b8f94af1df5425fc3d3d31c8775e9ac013d7db64ca0364d2d8730e0d1fa4ba73` |
