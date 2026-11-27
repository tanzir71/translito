# Windows 2.0.8

The first cloud transcript row has no detected language yet. Rendering it in
2.0.7 called `.upper()` on `None`, which aborted the desktop callback drain
before it could schedule another tick. Later source text, translations, subtitle
updates and Stop completion remained queued, even when Soniox had returned text.
Rows now tolerate an unknown language and update their badge when detection
arrives. A failed callback is reported through Tk's exception handler while
later callbacks and future ticks continue running.

With a cached Whisper model, 2.0.7 also automatically attached local language
detection to a cloud session. That detector ran synchronously for every
100 ms of capture. On the reported PC, individual detections took roughly
two seconds and sometimes misidentified the short opening audio. Capture
therefore fell behind, cloud received too little speech, and Stop waited for
busy workers. The previous release check forbade local model loading and
did not exercise this cached-model startup path.

Cloud now uses its provider's language identification by default. Cached
Whisper is not loaded or attached just because it is available. Local speech
detection and spending limits remain enabled. Local language filtering is an
explicit Cost & usage option, with its processing cost explained; saved
explicit choices are retained. Its changes take effect next session. Soniox
already receives the selected language hints and enables language identification
in its [stream configuration](https://docs.soniox.com/api-reference/stt/websocket-api).

Worker joins share a half-second default deadline instead of sequential
two- and five-second waits. Stopping a cost guard also prevents audio from a
late language-inspection result from opening a connection or being uploaded.
Text already produced remains available for saving.

Verification covers cached and missing local models, one-way and conversation
capture, stopping during a blocked inspection, bounded joins, and preserving an
explicit local-filter preference. Desktop regression checks render the initial
row with no language, update its source/translation/subtitles, complete Stop,
and inject a failed callback to verify subsequent events still run.
The packaged GUI is checked using the bundled
public Arabic sample through its real Start, capture, transcript and subtitle
paths, without recording customer audio or manually finalizing the stream.

The Windows installer remains unsigned. The macOS 1.0 DMG is retained.

The rebuilt executable was exercised with the installed native runtime,
RedirectionGuard enforced, cached Whisper Base present, and local model loading
forbidden. The real GUI's Start action captured only the bundled public Arabic
sample. Source text appeared after **4.73 seconds**, English translation after
**7.01 seconds**, and the native subtitle window was visible with text.
Stop returned the button to Start in **0.55 seconds** and the capture thread
exited. There were no callback errors, no local model loads and no manual
stream-finalize call. The frozen dependency probe passed all **21 checks**.

Final source verification passed **869 app checks and 29 download checks**.
The portable archive passed full CRC verification, every staged file-size
check, and source comparisons for all 27 checked production modules plus the
importable GUI. Engine data and bundled VB-CABLE resources match their sources.

Release source: `f789c090093b781b308ce30902bbac05755d9537`.
The landing page passed **64 checks** with the 2.0.8 download links.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.8.exe | 256,945,547 | `be09ad15a753db42213cec1a76f397f872c5cbd5acdda3841c0aceb3051ef202` |
| TranslitoPortable-2.0.8.zip | 374,108,923 | `93a1c01059993fe9f84507fa8b509bfdadfe003935aa511d250ed7d350602b89` |
