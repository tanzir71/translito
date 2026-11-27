# Windows 2.0.9

Subtitle prominence now follows the latest available translation. A newer
source-only draft no longer moves the translated line into the smaller history
style. The last readable translation remains available while more source drafts
arrive. The optional original line belongs to the displayed translation.

The current translation uses the full configured subtitle text size and a
semibold face, including during partial translation updates. Previous
translations and the original use smaller type. With the default 24-point
setting, the translation is 24 points and the original is 12 points. Before the
first translation, source text is secondary. Same-language speech remains a
primary line when translation is unnecessary.

Verification passed 51 desktop UI checks, including the subtitle, layout, scale,
first-cloud-row and Stop regressions. The actual frozen subtitle window was
checked with Windows RedirectionGuard enabled: translation 24 points, original
12 points, native window visible at the existing 720-pixel width, matching
original/translation text and no callback errors. No customer audio was captured.
All 21 frozen dependency checks passed. Only `subtitle_overlay` changes in the
embedded Python module archive; the other 9,750 modules retain their bytecode.

A desktop test fake now exposes only actual transcriber fields, preventing
timer-driven cost updates from reading auto-created mock values.

The Windows installer remains unsigned. The macOS 1.0 DMG is retained.

The portable archive passed full CRC verification and every staged file-size
check. All 28 checked production modules plus the importable GUI match source;
engine data and VB-CABLE resources match their sources. Release source:
`92528192f06a5c14b1f860148428d80710f629f0`.
The landing page passed 64 checks with the 2.0.9 download links.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| TranslitoSetup-2.0.9.exe | 256,936,916 | `6f0269824891708f17167ddf52a3d5f4231c03bbed248549d08990d82f9231ab` |
| TranslitoPortable-2.0.9.zip | 374,109,439 | `3f490f4b318065e95d3a889429135fdc206e941c78cc1554575f39bfb7ac3719` |
