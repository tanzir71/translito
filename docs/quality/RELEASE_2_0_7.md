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
